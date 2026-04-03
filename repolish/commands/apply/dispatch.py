from repolish.commands.apply.coordinator import coordinate_sessions
from repolish.commands.apply.display import (
    note_running_from_member,
    print_startup,
)
from repolish.commands.apply.options import ApplyCommandOptions, ApplyOptions
from repolish.commands.apply.session import run_session
from repolish.commands.apply.utils import CoordinateOptions
from repolish.config.topology import find_workspace_root


def apply_command(params: ApplyCommandOptions) -> int:
    """Entry point for the apply command.

    Handles the top-level routing logic before any real work begins:

    1. **Member auto-run** — if the current directory is a member of a
       monorepo and ``--standalone`` was not passed, print a dim note and
       re-run as ``coordinate_sessions(--member <rel>)`` from the root.
       This reuses the exact same code path as running from the root with
       ``--member``, ensuring correct overlays and context (root apply is
       skipped by the coordinator).
    2. **Standalone** — skip topology detection and note entirely; run a single
       session directly via :func:`run_session`.
    3. **Default** — delegate to :func:`coordinate_sessions`, which detects
       the repository topology and sequences sessions accordingly (root +
       members for a multi-project repo, or a single session for a plain
       project).

    Returns:
        0 on success, or the exit code returned by the underlying session runner.
    """
    config_path = params.config.resolve()
    config_dir = config_path.parent

    print_startup()

    # When running inside a monorepo member: re-run as --member from the root.
    # This reuses the exact same coordinator code path, giving providers the
    # correct mode='member' context and overlays.  The root apply is skipped.
    if not params.standalone:
        root = find_workspace_root(config_dir)
        if root is not None:
            rel = config_dir.relative_to(root) if config_dir.is_relative_to(root) else config_dir
            note_running_from_member(config_dir, root, rel)
            return coordinate_sessions(
                (root / 'repolish.yaml').resolve(),
                CoordinateOptions(
                    check_only=params.check,
                    strict=params.strict,
                    member=str(rel),
                    skip_post_process=params.skip_post_process,
                ),
            )

    # --standalone: single-session only, no note printed.
    if params.standalone:
        return run_session(
            ApplyOptions(
                config_path=config_path,
                check_only=params.check,
                strict=params.strict,
                skip_post_process=params.skip_post_process,
            ),
        )

    return coordinate_sessions(
        config_path,
        CoordinateOptions(
            check_only=params.check,
            strict=params.strict,
            member=params.member,
            root_only=params.root_only,
            skip_post_process=params.skip_post_process,
        ),
    )
