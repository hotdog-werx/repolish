from pathlib import Path

import typer
from hotlog import get_logger

from repolish.cli.utils import run_cli_command
from repolish.commands.link import command

logger = get_logger(__name__)

# Module-level constants for Typer options to avoid B008
CONFIG_OPTION = typer.Option(
    Path('repolish.yaml'),
    '--config',
    help='Path to the repolish YAML configuration file',
)


def link(
    config: Path = CONFIG_OPTION,
) -> None:
    """Link provider resources to the project."""
    # Logging is already configured by setup_logging in CLI entry points
    run_cli_command(lambda: command(config))
