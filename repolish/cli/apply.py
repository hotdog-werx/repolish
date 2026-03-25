from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command


@Parameter(name='*')
class ApplyParams(BaseModel):
    """Parameters for the apply command."""

    config: Annotated[Path, Parameter(name=['--config', '-c'])] = Field(
        default=Path('repolish.yaml'),
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
            'Bypass monorepo detection entirely and suppress the member note. '
            'Run a normal single-pass repolish on the current directory.'
        ),
    )


_DEFAULT_APPLY_PARAMS = ApplyParams()


def apply(params: ApplyParams = _DEFAULT_APPLY_PARAMS) -> None:
    """Apply templates to project."""
    # Deferred so that importing this CLI module (e.g. when running `repolish lint`)
    # does not eagerly load the entire apply command tree.
    from repolish.commands.apply import ApplyCommandOptions, apply_command  # noqa: PLC0415

    run_cli_command(
        lambda: apply_command(
            ApplyCommandOptions(
                config=params.config,
                check=params.check,
                strict=params.strict,
                root_only=params.root_only,
                member=params.member,
                standalone=params.standalone,
            ),
        ),
    )
