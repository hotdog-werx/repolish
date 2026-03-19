from repolish.commands.apply.coordinator import coordinate_sessions
from repolish.commands.apply.display import error_running_from_member
from repolish.commands.apply.options import ApplyCommandOptions, ApplyOptions
from repolish.commands.apply.session import run_session
from repolish.config.topology import find_workspace_root


def apply_command(params: ApplyCommandOptions) -> int:
    """Entry point for the apply command.

    Handles the top-level routing logic before any real work begins:

    1. **Member guard** — if the current directory is a member of a
       monorepo and ``--standalone`` was not passed, print an actionable
       error and exit early.  Running from a member directly would bypass
       the root session and break cross-session input routing.
    2. **Standalone** — skip topology detection entirely and run a single
       session directly via :func:`run_session`.
    3. **Default** — delegate to :func:`coordinate_sessions`, which detects
       the repository topology and sequences sessions accordingly (root +
       members for a multi-project repo, or a single session for a plain
       project).

    Returns:
        0 on success, 1 on a guard/validation error, or the exit code
        returned by the underlying session runner.
    """
    config_path = params.config.resolve()
    config_dir = config_path.parent

    # Warn when running inside a monorepo member without --standalone.
    if not params.standalone:
        root = find_workspace_root(config_dir)
        if root is not None:
            rel = config_dir.relative_to(root) if config_dir.is_relative_to(root) else config_dir
            error_running_from_member(config_dir, root, rel)
            return 1

    # --standalone: single-session only, no multiple session coordination.
    if params.standalone:
        return run_session(
            ApplyOptions(
                config_path=config_path,
                check_only=params.check,
                strict=params.strict,
            ),
        )

    return coordinate_sessions(
        config_path,
        check_only=params.check,
        strict=params.strict,
        member=params.member,
        root_only=params.root_only,
    )
