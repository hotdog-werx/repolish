from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command


@Parameter(name='*')
class LintParams(BaseModel):
    """Parameters for the lint command.

    Every field carries an explicit cyclopts ``Parameter`` name: the docs
    insertion renderer (``internal/local_provider/docs_insertions.py``)
    reads them to build the lint argument table, and it refuses fields
    whose names would have to be derived.
    """

    provider_dir: Annotated[Path, Parameter(name='PROVIDER_DIR')] = Field(
        description='Path to the provider root directory containing repolish.py',
    )


def lint(params: LintParams) -> None:
    """Lint a provider's templates against its context model."""
    # Deferred so that importing this CLI module does not eagerly load the lint
    # command tree when a different subcommand (e.g. apply) is invoked.
    from repolish.commands.lint import command  # noqa: PLC0415

    run_cli_command(lambda: command(params.provider_dir))
