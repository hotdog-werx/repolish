from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command
from repolish.commands.apply import command


@Parameter(name='*')
class ApplyParams(BaseModel):
    """Parameters for the apply command."""

    config: Annotated[Path, Parameter(name=['--config', '-c'])] = Field(
        Path('repolish.yaml'),
        description='Path to the repolish YAML configuration file',
    )
    check: bool = Field(
        default=False,
        description='Load config and create context (dry-run check)',
    )
    strict: bool = Field(
        default=False,
        description='Exit with an error if any provider could not be registered (useful for CI)',
    )
    root_only: bool = Field(
        default=False,
        description='Run only the root pass; skip member passes (mutually exclusive with --member)',
    )
    member: str | None = Field(
        default=None,
        description=(
            'Run only the specified member full pass (repo-relative path or package name). '
            'The root pass is skipped. Mutually exclusive with --root-only.'
        ),
    )
    standalone: bool = Field(
        default=False,
        description=(
            'Bypass monorepo detection entirely. Run a normal single-pass repolish on the '
            'current directory. Use this from inside a member directory to override the R10 guard.'
        ),
    )


_DEFAULT_APPLY_PARAMS = ApplyParams()


def apply(params: ApplyParams = _DEFAULT_APPLY_PARAMS) -> None:
    """Apply templates to project."""

    def _run() -> int:
        config_path = params.config.resolve()
        config_dir = config_path.parent

        # R10 guard: warn when running inside a monorepo member without --standalone.
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
                config_path,
                check_only=params.check,
                strict=params.strict,
            )

        from repolish.commands.monorepo import run_monorepo  # noqa: PLC0415

        return run_monorepo(
            config_path,
            check_only=params.check,
            strict=params.strict,
            member=params.member,
            root_only=params.root_only,
        )

    run_cli_command(_run)
