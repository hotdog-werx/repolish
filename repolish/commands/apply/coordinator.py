import contextlib
import filecmp
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from hotlog import get_logger

from repolish.commands.apply.display import (
    error_unknown_member,
    print_summary_tree,
)
from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.commands.apply.pipeline import resolve_session
from repolish.commands.apply.session import apply_session, run_session
from repolish.config.loader import load_config_file
from repolish.config.topology import (
    detect_workspace,
    detect_workspace_from_config,
)
from repolish.providers.models import (
    GlobalContext,
    TemplateMapping,
    get_global_context,
)
from repolish.providers.models.context import MemberInfo, WorkspaceContext
from repolish.providers.models.files import FileMode, FileRecord

logger = get_logger(__name__)


@contextlib.contextmanager
def _chdir(path: Path) -> Iterator[None]:
    """Context manager that temporarily changes the working directory."""
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


def _build_global_context(mono_ctx: WorkspaceContext) -> GlobalContext:
    """Return a :class:`GlobalContext` with the given :class:`WorkspaceContext` injected."""
    base = get_global_context()
    return base.model_copy(update={'workspace': mono_ctx})


# ---------------------------------------------------------------------------
# Promotion helpers
# ---------------------------------------------------------------------------


def _resolve_source_file(
    source_template: str,
    member_render_dir: Path,
) -> Path | None:
    """Return the rendered source file path for a promoted mapping, or None if missing."""
    prefix = '_repolish.'
    source_file = member_render_dir / source_template
    if source_file.exists():
        return source_file
    from pathlib import PurePosixPath

    cand = PurePosixPath(source_template)
    prefixed = member_render_dir / str(cand.parent) / (prefix + cand.name)
    if prefixed.exists():
        return prefixed
    return None


def _apply_promotion_pass(
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
    root_session: ResolvedSession,
    *,
    check_only: bool,
) -> int:
    """Collect and apply (or check) files promoted from member sessions to the root.

    Iterates ``promoted_file_mappings`` from each member session, resolves
    conflicts using the ``promote_conflict`` strategy, then either diffs the
    promoted files against disk (``check_only=True``) or writes them.  Root's
    own ``file_mappings`` always wins: any promoted path present in the root
    session's ``file_mappings`` is silently skipped here.

    Results are stored on ``root_session.promoted_records`` and
    ``root_session.promoted_apply_result``.

    Returns 0 on success, non-zero on conflict or check failure.
    """
    root_base_dir = root_session.config.config_dir

    # Paths owned by the root session's own create_file_mappings — these win.
    root_owned_paths: set[str] = set(
        root_session.providers.file_mappings.keys(),
    )

    # winner: dest -> (rendered_source_path, member_name, mapping)
    winners: dict[str, tuple[Path, str, TemplateMapping]] = {}

    for m, session, _opts in member_sessions:
        member_name = m.name
        member_render_dir = session.config.config_dir / '.repolish' / '_' / 'render' / 'repolish'

        for (
            dest,
            mapping_val,
        ) in session.providers.promoted_file_mappings.items():
            if isinstance(mapping_val, str):
                mapping = TemplateMapping(source_template=mapping_val)
            else:
                mapping = mapping_val

            if not mapping.source_template:
                continue

            source_file = _resolve_source_file(
                mapping.source_template,
                member_render_dir,
            )
            if source_file is None:
                logger.warning(
                    'promoted_source_not_found',
                    dest=dest,
                    source=mapping.source_template,
                    member=member_name,
                )
                continue

            if dest in winners:
                prev_path, prev_member, prev_mapping = winners[dest]
                strategy: Literal['identical', 'last_wins', 'error'] = mapping.promote_conflict

                if strategy == 'error':
                    logger.error(
                        'promote_conflict_error',
                        dest=dest,
                        member_a=prev_member,
                        member_b=member_name,
                        suggestion='set promote_conflict="last_wins" to suppress this',
                    )
                    return 1
                if strategy == 'last_wins':
                    winners[dest] = (source_file, member_name, mapping)
                elif not filecmp.cmp(
                    str(prev_path),
                    str(source_file),
                    shallow=False,
                ):
                    logger.error(
                        'promote_conflict_not_identical',
                        dest=dest,
                        member_a=prev_member,
                        member_b=member_name,
                        suggestion=(
                            'both members rendered different content; '
                            'set promote_conflict="last_wins" or resolve the template divergence'
                        ),
                    )
                    return 1
                    # identical — keep first winner, no-op
            else:
                winners[dest] = (source_file, member_name, mapping)

    promoted_records: list[FileRecord] = []
    promoted_result: dict[str, str] = {}

    for dest, (source_file, member_name, mapping) in winners.items():
        if dest in root_owned_paths:
            # Root's own mapping wins; annotate the root FileRecord instead.
            for i, rec in enumerate(root_session.providers.file_records):
                if rec.path == dest:
                    root_session.providers.file_records[i] = FileRecord(
                        path=rec.path,
                        mode=rec.mode,
                        owner=rec.owner,
                        source=rec.source,
                        overlay_dir=rec.overlay_dir,
                        promoted_from=member_name,
                        overridden_by=rec.owner,
                    )
                    break
            promoted_records.append(
                FileRecord(
                    path=dest,
                    mode=FileMode.REGULAR,
                    owner=member_name,
                    source=mapping.source_template,
                    promoted_from=member_name,
                    overridden_by='root' if dest in root_session.providers.file_mappings else None,
                ),
            )
            promoted_result[dest] = 'overridden_by_root'
            continue

        dest_file = root_base_dir / dest

        if check_only:
            if not dest_file.exists() or not filecmp.cmp(
                str(source_file),
                str(dest_file),
                shallow=False,
            ):
                promoted_result[dest] = 'differs'
                logger.info(
                    'promoted_file_differs',
                    dest=dest,
                    member=member_name,
                    _display_level=1,
                )
            else:
                promoted_result[dest] = 'unchanged'
        else:
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            if dest_file.exists() and filecmp.cmp(
                str(source_file),
                str(dest_file),
                shallow=False,
            ):
                promoted_result[dest] = 'unchanged'
            else:
                shutil.copy2(source_file, dest_file)
                promoted_result[dest] = 'written'
                logger.info(
                    'promoted_file_written',
                    dest=dest,
                    member=member_name,
                    source=str(source_file),
                    _display_level=1,
                )

        promoted_records.append(
            FileRecord(
                path=dest,
                mode=FileMode.REGULAR,
                owner=member_name,
                source=mapping.source_template,
                promoted_from=member_name,
            ),
        )

    root_session.promoted_records = promoted_records
    root_session.promoted_apply_result = promoted_result

    if check_only:
        differs = [d for d, s in promoted_result.items() if s == 'differs']
        if differs:
            logger.warning(
                'promoted_files_out_of_date',
                files=sorted(differs),
                suggestion='run `repolish apply` to apply promoted changes',
            )
            return 2
    return 0


def coordinate_sessions(
    config_path: Path,
    *,
    check_only: bool,
    strict: bool = False,
    member: str | None = None,
    root_only: bool = False,
    skip_post_process: bool = False,
) -> int:
    """Orchestrate a full repolish run for a standalone project or monorepo.

    Resolve phase:
    1. Detect workspace topology.
    2. If standalone → run single session via :func:`run_session`.
    3. Resolve every member session.  Each :func:`resolve_session` call
       internally performs a dry pass that captures the outward cross-session
       data (``provider_entries`` + ``emitted_inputs``) alongside the full
       provider state.
    4. Resolve the root session with all member data injected.

    Apply phase:
    5. Apply root session (skipped when ``--member`` is given).
    6. Apply each member session (skipped when ``--root-only``).

    The clear separation between resolve and apply lets callers inspect the
    complete set of :class:`~repolish.commands.apply.options.ResolvedSession`
    objects — and the cross-session data flows between them — before any files
    are written.
    """
    config_dir = config_path.resolve().parent
    raw_config = load_config_file(config_path)

    if raw_config.workspace and raw_config.workspace.members:
        mono_ctx = detect_workspace_from_config(
            config_dir,
            raw_config.workspace,
        )
    else:
        mono_ctx = detect_workspace(config_dir)

    if mono_ctx is None:
        # Standalone project — single session, no coordination needed.
        return run_session(
            ApplyOptions(
                config_path=config_path.resolve(),
                check_only=check_only,
                strict=strict,
                skip_post_process=skip_post_process,
            ),
        )

    # Validate --member filter.
    if member:
        matching = [m for m in mono_ctx.members if str(m.path) == member or m.name == member]
        if not matching:
            error_unknown_member(member, [m.name for m in mono_ctx.members])
            return 1

    # ── RESOLVE PHASE ──────────────────────────────────────────────────────────
    # Resolve every member session.  Each call runs an internal dry pass that
    # captures what the member contributes outward (provider_entries +
    # emitted_inputs) alongside the full provider state.
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]] = []
    for m in mono_ctx.members:
        member_dir = (config_dir / m.path).resolve()
        pkg_mono_ctx = WorkspaceContext(
            mode='member',
            root_dir=config_dir,
            package_dir=member_dir,
            members=mono_ctx.members,
        )
        opts = ApplyOptions(
            config_path=(member_dir / 'repolish.yaml').resolve(),
            check_only=check_only,
            strict=strict,
            skip_post_process=skip_post_process,
            global_context=_build_global_context(pkg_mono_ctx),
        )
        with _chdir(member_dir):
            session = resolve_session(opts)
        member_sessions.append((m, session, opts))

    # Aggregate outward cross-session data from all member sessions for root.
    all_member_entries = [e for _, s, _ in member_sessions for e in s.provider_entries]
    all_member_inputs = [i for _, s, _ in member_sessions for i in s.emitted_inputs]

    # Resolve root session with member data injected so root providers see the
    # complete member picture during context finalization.
    root_mono_ctx = WorkspaceContext(
        mode='root',
        root_dir=config_dir,
        members=mono_ctx.members,
    )
    root_opts = ApplyOptions(
        config_path=config_path.resolve(),
        check_only=check_only,
        strict=strict,
        skip_post_process=skip_post_process,
        global_context=_build_global_context(root_mono_ctx),
        extra_provider_entries=all_member_entries or None,
        extra_inputs=all_member_inputs or None,
    )
    with _chdir(config_dir):
        root_session = resolve_session(root_opts)

    # ── APPLY PHASE ────────────────────────────────────────────────────────────
    # Apply order: members first, then root.  This is required so that member
    # render directories exist when the promotion pass collects promoted files.
    # Root and members write to independent directories so the flip is safe.
    # Display order (summary tree) remains root-first for readability.
    completed_sessions: list[ResolvedSession] = []

    # Apply members (unless --root-only); honour the --member filter.
    if not root_only:
        for m, session, opts in member_sessions:
            if member and (str(m.path) != member and m.name != member):
                continue
            with _chdir(opts.config_path.parent):
                rc = apply_session(
                    session,
                    check_only=check_only,
                    skip_post_process=skip_post_process,
                )
            if rc != 0:
                return rc
            completed_sessions.append(session)

    # Promotion pass: collect promoted files from all applied member sessions
    # and apply (or diff) them at the repo root before the root apply runs.
    # Skipped when --member is given (root pass is suppressed in that case).
    if not member:
        rc = _apply_promotion_pass(
            member_sessions,
            root_session,
            check_only=check_only,
        )
        if rc not in (0, 2):
            return rc
        promotion_check_rc = rc

        # Apply root (unless --member is given).
        with _chdir(config_dir):
            rc = apply_session(
                root_session,
                check_only=check_only,
                skip_post_process=skip_post_process,
            )
        if rc != 0:
            return rc
        if check_only and promotion_check_rc == 2:
            # Promoted files were out of date; propagate the check failure.
            completed_sessions.append(root_session)
            print_summary_tree(completed_sessions)
            return 2
        completed_sessions.append(root_session)

    print_summary_tree(completed_sessions)
    return 0
