from pathlib import Path

import typer

from repolish.cli.utils import run_cli_command
from repolish.commands.apply import command

# Module-level constants for Typer options to avoid B008
DEFAULT_CONFIG = Path('repolish.yaml')
CONFIG_OPTION = typer.Option(
    DEFAULT_CONFIG,
    '--config',
    help='Path to the repolish YAML configuration file',
)
CHECK_OPTION = typer.Option(
    default=False,
    help='Load config and create context (dry-run check)',
)


def apply(
    config: Path = CONFIG_OPTION,
    *,
    check: bool = CHECK_OPTION,
) -> None:
    """Apply templates to project."""
    run_cli_command(lambda: command(config, check_only=check))
