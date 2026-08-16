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
    fail_on_warnings: bool = Field(
        default=False,
        description='Treat validator warnings as fatal errors (useful for CI)',
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
    skip_post_process: bool = Field(
        default=False,
        description='Skip all post_process commands defined in repolish.yaml',
    )
    providers: Annotated[str | None, Parameter(name=['--providers', '-p'])] = Field(
        default=None,
        description='Comma-separated list of provider aliases to run (e.g., -p databricks,python)',
    )


_DEFAULT_APPLY_PARAMS = ApplyParams()


def apply(params: ApplyParams = _DEFAULT_APPLY_PARAMS) -> None:
    """Apply templates to project."""
    # Deferred so that importing this CLI module (e.g. when running `repolish lint`)
    # does not eagerly load the entire apply command tree.
    from repolish.commands.apply import ApplyCommandOptions, apply_command  # noqa: PLC0415

    # Parse comma-separated providers list
    provider_filter = None
    if params.providers:
        provider_filter = [p.strip() for p in params.providers.split(',') if p.strip()]

    run_cli_command(
        lambda: apply_command(
            ApplyCommandOptions(
                config=params.config,
                check=params.check,
                fail_on_warnings=params.fail_on_warnings,
                root_only=params.root_only,
                member=params.member,
                standalone=params.standalone,
                skip_post_process=params.skip_post_process,
                provider_filter=provider_filter,
            ),
        ),
    )
