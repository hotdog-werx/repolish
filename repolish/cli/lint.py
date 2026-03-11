from pathlib import Path

import typer

from repolish.cli.utils import run_cli_command
from repolish.commands.lint import command

PROVIDER_DIR_ARG = typer.Argument(
    help='Path to the provider root directory containing repolish.py',
)


def lint(
    provider_dir: Path = PROVIDER_DIR_ARG,
) -> None:
    """Lint a provider's templates against its context model."""
    run_cli_command(lambda: command(provider_dir))  # pragma: no cover
