from __future__ import annotations

import filecmp
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from hotlog import get_logger

from repolish.commands.apply.display import (
    error_unknown_member,
    print_summary_tree,
)
from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.commands.apply.pipeline import resolve_session
from repolish.commands.apply.session import apply_session, run_session
from repolish.commands.apply.utils import (
    CoordinateOptions,
    build_global_context,
    chdir,
)
from repolish.config.loader import load_config_file
from repolish.config.topology import (
    detect_workspace,
    detect_workspace_from_config,
)
from repolish.providers.models import (
    TemplateMapping,
)
from repolish.providers.models.context import MemberInfo, WorkspaceContext
from repolish.providers.models.files import FileMode, FileRecord

if TYPE_CHECKING:
    from collections.abc import Iterator

    from repolish.config.models import RepolishConfigFile

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Promotion helpers
# ---------------------------------------------------------------------------


@dataclass
class PromotionWinner:
    """A resolved promoted file ready to be written (or checked) at the repo root."""

    dest: str
    source_file: Path
    member_name: str
    mapping: TemplateMapping


def _resolve_source_file(
    source_template: str,
    member_render_dir: Path,
) -> Path | None:
    """Return the rendered source file path for a promoted mapping, or None if missing."""
    source_file = member_render_dir / source_template
    if source_file.exists():
        return source_file
    cand = PurePosixPath(source_template)
    prefixed = member_render_dir / str(cand.parent) / ('_repolish.' + cand.name)
    if prefixed.exists():
        return prefixed
    return None


def _conflict_winner(
    dest: str,
    prev: PromotionWinner,
    challenger: PromotionWinner,
) -> PromotionWinner | None:
    """Return the winning entry after resolving a promotion conflict, or None on hard error."""
    strategy = challenger.mapping.promote_conflict
    if strategy == 'error':
        logger.error(
            'promote_conflict_error',
            dest=dest,
            member_a=prev.member_name,
            member_b=challenger.member_name,
            suggestion='set promote_conflict="last_wins" to suppress this',
        )
        return None
    if strategy == 'last_wins':
        return challenger
    if not filecmp.cmp(
        str(prev.source_file),
        str(challenger.source_file),
        shallow=False,
    ):
        logger.error(
            'promote_conflict_not_identical',
            dest=dest,
            member_a=prev.member_name,
            member_b=challenger.member_name,
            suggestion=(
                'both members rendered different content; '
                'set promote_conflict="last_wins" or resolve the template divergence'
            ),
        )
        return None
    return prev  # identical — keep first winner


def _normalize_mapping(mapping_val: str | TemplateMapping) -> TemplateMapping:
    """Coerce a string shorthand into a :class:`TemplateMapping`."""
    return TemplateMapping(source_template=mapping_val) if isinstance(mapping_val, str) else mapping_val


def _iter_pending_promotions(
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
) -> Iterator[PromotionWinner]:
    """Yield a :class:`PromotionWinner` for each valid promoted mapping across all members."""
    for m, session, _opts in member_sessions:
        member_render_dir = session.config.config_dir / '.repolish' / '_' / 'render' / 'repolish'
        for (
            dest,
            mapping_val,
        ) in session.providers.promoted_file_mappings.items():
            mapping = _normalize_mapping(mapping_val)
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
                    member=m.name,
                )
                continue
            yield PromotionWinner(
                dest=dest,
                source_file=source_file,
                member_name=m.name,
                mapping=mapping,
            )


def _collect_promotion_winners(
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
) -> dict[str, PromotionWinner] | None:
    """Return the winning source for each promoted destination, or ``None`` on hard conflict."""
    winners: dict[str, PromotionWinner] = {}

    for winner in _iter_pending_promotions(member_sessions):
        if winner.dest not in winners:
            winners[winner.dest] = winner
            continue
        result = _conflict_winner(winner.dest, winners[winner.dest], winner)
        if result is None:
            return None
        winners[winner.dest] = result

    return winners


def _record_root_override(
    winner: PromotionWinner,
    root_session: ResolvedSession,
) -> FileRecord:
    """Mark a root-owned dest as overridden and return the member's promoted FileRecord."""
    for i, rec in enumerate(root_session.providers.file_records):
        if rec.path == winner.dest:
            root_session.providers.file_records[i] = FileRecord(
                path=rec.path,
                mode=rec.mode,
                owner=rec.owner,
                source=rec.source,
                overlay_dir=rec.overlay_dir,
                promoted_from=winner.member_name,
                overridden_by=rec.owner,
            )
            break
    return FileRecord(
        path=winner.dest,
        mode=FileMode.REGULAR,
        owner=winner.member_name,
        source=winner.mapping.source_template,
        promoted_from=winner.member_name,
        overridden_by='root',
    )


def _apply_promoted_file(
    winner: PromotionWinner,
    dest_file: Path,
    *,
    check_only: bool,
) -> tuple[FileRecord, str]:
    """Check or write a single promoted file. Returns ``(record, status)``."""
    if check_only:
        if not dest_file.exists() or not filecmp.cmp(
            str(winner.source_file),
            str(dest_file),
            shallow=False,
        ):
            logger.info(
                'promoted_file_differs',
                dest=winner.dest,
                member=winner.member_name,
                _display_level=1,
            )
            result = 'differs'
        else:
            result = 'unchanged'
    else:
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        if dest_file.exists() and filecmp.cmp(
            str(winner.source_file),
            str(dest_file),
            shallow=False,
        ):
            result = 'unchanged'
        else:
            shutil.copy2(winner.source_file, dest_file)
            logger.info(
                'promoted_file_written',
                dest=winner.dest,
                member=winner.member_name,
                source=str(winner.source_file),
                _display_level=1,
            )
            result = 'written'

    record = FileRecord(
        path=winner.dest,
        mode=FileMode.REGULAR,
        owner=winner.member_name,
        source=winner.mapping.source_template,
        promoted_from=winner.member_name,
    )
    return record, result


def _apply_winners(
    winners: dict[str, PromotionWinner],
    root_session: ResolvedSession,
    *,
    check_only: bool,
) -> tuple[list[FileRecord], dict[str, str]]:
    """Write (or diff) each winning promoted file at the repo root.

    Root-owned destinations are skipped and annotated as overridden instead.
    Returns ``(promoted_records, promoted_result)``.
    """
    root_base_dir = root_session.config.config_dir
    root_owned_paths = set(root_session.providers.file_mappings.keys())
    promoted_records: list[FileRecord] = []
    promoted_result: dict[str, str] = {}

    for dest, winner in winners.items():
        if dest in root_owned_paths:
            promoted_records.append(_record_root_override(winner, root_session))
            promoted_result[dest] = 'overridden_by_root'
            continue

        record, result = _apply_promoted_file(
            winner,
            root_base_dir / dest,
            check_only=check_only,
        )
        promoted_records.append(record)
        promoted_result[dest] = result

    return promoted_records, promoted_result


def _apply_promotion_pass(
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
    root_session: ResolvedSession,
    *,
    check_only: bool,
) -> int:
    """Collect and apply (or check) files promoted from member sessions to the root.

    Returns 0 on success, 1 on hard conflict, 2 when check-only finds stale files.
    Results are stored on ``root_session.promoted_records`` and
    ``root_session.promoted_apply_result``.
    """
    winners = _collect_promotion_winners(member_sessions)
    if winners is None:
        return 1

    promoted_records, promoted_result = _apply_winners(
        winners,
        root_session,
        check_only=check_only,
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


# ---------------------------------------------------------------------------
# Coordinate helpers — workspace detection, resolve and apply phases
# ---------------------------------------------------------------------------


def _detect_workspace(
    raw_config: RepolishConfigFile,
    config_dir: Path,
) -> WorkspaceContext | None:
    """Detect the workspace topology from config, falling back to filesystem scan."""
    if raw_config.workspace and raw_config.workspace.members:
        return detect_workspace_from_config(config_dir, raw_config.workspace)
    return detect_workspace(config_dir)


def _validate_member_filter(mono_ctx: WorkspaceContext, member: str) -> bool:
    """Return True when *member* matches at least one workspace member.

    Logs an error and returns False when the name is unknown.
    """
    if any(m.path.as_posix() == member or str(m.path) == member or m.name == member for m in mono_ctx.members):
        return True
    error_unknown_member(member, [m.name for m in mono_ctx.members])
    return False


def _resolve_member_sessions(
    mono_ctx: WorkspaceContext,
    config_dir: Path,
    opts: CoordinateOptions,
) -> list[tuple[MemberInfo, ResolvedSession, ApplyOptions]]:
    """Resolve every member session, returning a list of (member, session, opts) triples."""
    sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]] = []
    for m in mono_ctx.members:
        member_dir = (config_dir / m.path).resolve()
        workspace = WorkspaceContext(
            mode='member',
            root_dir=config_dir,
            package_dir=member_dir,
            members=mono_ctx.members,
        )
        apply_opts = ApplyOptions(
            config_path=(member_dir / 'repolish.yaml').resolve(),
            check_only=opts.check_only,
            strict=opts.strict,
            skip_post_process=opts.skip_post_process,
            global_context=build_global_context(workspace),
        )
        with chdir(member_dir):
            session = resolve_session(apply_opts)
        sessions.append((m, session, apply_opts))
    return sessions


def _resolve_root_session(
    config_path: Path,
    mono_ctx: WorkspaceContext,
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
    config_dir: Path,
    opts: CoordinateOptions,
) -> ResolvedSession:
    """Resolve the root session with all member data injected."""
    all_member_entries = [e for _, s, _ in member_sessions for e in s.provider_entries]
    all_member_inputs = [i for _, s, _ in member_sessions for i in s.emitted_inputs]
    workspace = WorkspaceContext(
        mode='root',
        root_dir=config_dir,
        members=mono_ctx.members,
    )
    apply_opts = ApplyOptions(
        config_path=config_path.resolve(),
        check_only=opts.check_only,
        strict=opts.strict,
        skip_post_process=opts.skip_post_process,
        global_context=build_global_context(workspace),
        extra_provider_entries=all_member_entries or None,
        extra_inputs=all_member_inputs or None,
    )
    with chdir(config_dir):
        return resolve_session(apply_opts)


def _apply_member_sessions(
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
    opts: CoordinateOptions,
) -> tuple[int, list[ResolvedSession]]:
    """Apply each member session, honouring opts.member as a filter. Returns ``(rc, completed)``."""
    completed: list[ResolvedSession] = []
    for m, session, apply_opts in member_sessions:
        if opts.member and str(m.path) != opts.member and m.name != opts.member:
            continue
        with chdir(apply_opts.config_path.parent):
            rc = apply_session(
                session,
                check_only=opts.check_only,
                skip_post_process=opts.skip_post_process,
            )
        if rc != 0:
            return rc, completed
        completed.append(session)
    return 0, completed


def _run_root_pass(
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
    root_session: ResolvedSession,
    config_dir: Path,
    completed_sessions: list[ResolvedSession],
    opts: CoordinateOptions,
) -> int:
    """Run the promotion pass then apply the root session; append root to completed on success.

    Returns 0 on clean success, 2 when check-only finds promoted files out of date,
    or 1 on a hard promotion conflict.  Non-zero from apply_session is propagated as-is.
    """
    rc = _apply_promotion_pass(
        member_sessions,
        root_session,
        check_only=opts.check_only,
    )
    if rc not in (0, 2):
        return rc
    promotion_stale = opts.check_only and rc == 2

    with chdir(config_dir):
        rc = apply_session(
            root_session,
            check_only=opts.check_only,
            skip_post_process=opts.skip_post_process,
        )
    if rc != 0:
        return rc

    completed_sessions.append(root_session)
    return 2 if promotion_stale else 0


def _run_apply_phase(
    member_sessions: list[tuple[MemberInfo, ResolvedSession, ApplyOptions]],
    root_session: ResolvedSession,
    config_dir: Path,
    opts: CoordinateOptions,
) -> tuple[int, list[ResolvedSession]]:
    """Run the member and root apply phases; return ``(rc, completed_sessions)``."""
    completed: list[ResolvedSession] = []
    if not opts.root_only:
        rc, done = _apply_member_sessions(member_sessions, opts)
        if rc != 0:
            return rc, completed
        completed.extend(done)
    if not opts.member:
        rc = _run_root_pass(
            member_sessions,
            root_session,
            config_dir,
            completed,
            opts,
        )
        if rc not in (0, 2):
            return rc, completed
        return rc, completed
    return 0, completed


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def coordinate_sessions(config_path: Path, opts: CoordinateOptions) -> int:
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
    mono_ctx = _detect_workspace(raw_config, config_dir)

    if mono_ctx is None:
        return run_session(
            ApplyOptions(
                config_path=config_path.resolve(),
                check_only=opts.check_only,
                strict=opts.strict,
                skip_post_process=opts.skip_post_process,
            ),
        )

    if opts.member and not _validate_member_filter(mono_ctx, opts.member):
        return 1

    member_sessions = _resolve_member_sessions(mono_ctx, config_dir, opts)
    root_session = _resolve_root_session(
        config_path,
        mono_ctx,
        member_sessions,
        config_dir,
        opts,
    )

    rc, completed_sessions = _run_apply_phase(
        member_sessions,
        root_session,
        config_dir,
        opts,
    )
    print_summary_tree(completed_sessions)
    return rc
