from pathlib import Path
from typing import Annotated

from cyclopts import Parameter

from repolish.cli.utils import run_cli_command
from repolish.commands.lint import command


def lint(
    provider_dir: Annotated[
        Path,
        Parameter(
            help='Path to the provider root directory containing repolish.py',
        ),
    ],
) -> None:
    """Lint a provider's templates against its context model."""
    run_cli_command(lambda: command(provider_dir))
