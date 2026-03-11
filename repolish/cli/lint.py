from pathlib import Path

from cyclopts import Parameter
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command
from repolish.commands.lint import command


@Parameter(name='*')
class LintParams(BaseModel):
    """Parameters for the lint command."""

    provider_dir: Path = Field(
        description='Path to the provider root directory containing repolish.py',
    )


def lint(params: LintParams) -> None:
    """Lint a provider's templates against its context model."""
    run_cli_command(lambda: command(params.provider_dir))
