from repolish.commands.apply.command import command
from repolish.commands.apply.monorepo import run_monorepo
from repolish.commands.apply.options import ApplyCommandOptions, ApplyOptions


def apply_command(params: ApplyCommandOptions) -> int:
    config_path = params.config.resolve()
    config_dir = config_path.parent

    # Guard: warn when running inside a monorepo member without --standalone.
    if not params.standalone:
        from repolish.config.monorepo import check_running_from_member  # noqa: PLC0415

        root = check_running_from_member(config_dir)
        if root is not None:
            import sys  # noqa: PLC0415

            rel = config_dir.relative_to(root) if config_dir.is_relative_to(root) else config_dir
            print(  # noqa: T201
                f'error: {config_dir} is a member of the monorepo rooted at {root}.\n'
                f'Run `repolish apply` from the root, or use '
                f'`repolish apply --member {rel}` from the root.\n'
                f'Pass --standalone to bypass this check and run a single-pass apply here.',
                file=sys.stderr,
            )
            return 1

    # --standalone: single-pass only, no monorepo orchestration.
    if params.standalone:
        return command(
            ApplyOptions(
                config_path=config_path,
                check_only=params.check,
                strict=params.strict,
            ),
        )

    return run_monorepo(
        config_path,
        check_only=params.check,
        strict=params.strict,
        member=params.member,
        root_only=params.root_only,
    )
