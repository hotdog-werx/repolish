import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

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
from repolish.providers.models import GlobalContext, get_global_context
from repolish.providers.models.context import MemberInfo, WorkspaceContext


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


def coordinate_sessions(
    config_path: Path,
    *,
    check_only: bool,
    strict: bool = False,
    member: str | None = None,
    root_only: bool = False,
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
        global_context=_build_global_context(root_mono_ctx),
        extra_provider_entries=all_member_entries or None,
        extra_inputs=all_member_inputs or None,
    )
    with _chdir(config_dir):
        root_session = resolve_session(root_opts)

    # ── APPLY PHASE ────────────────────────────────────────────────────────────
    completed_sessions: list[ResolvedSession] = []

    # Apply root (unless --member is given).
    if not member:
        with _chdir(config_dir):
            rc = apply_session(root_session, check_only=check_only)
        if rc != 0:
            return rc
        completed_sessions.append(root_session)

    # Apply members (unless --root-only); honour the --member filter.
    if not root_only:
        for m, session, opts in member_sessions:
            if member and (str(m.path) != member and m.name != member):
                continue
            with _chdir(opts.config_path.parent):
                rc = apply_session(session, check_only=check_only)
            if rc != 0:
                return rc
            completed_sessions.append(session)

    print_summary_tree(completed_sessions)
    return 0
