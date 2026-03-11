from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger

from repolish.cli.utils import run_cli_command
from repolish.commands.link import command

logger = get_logger(__name__)

_DEFAULT_CONFIG = Path('repolish.yaml')


def link(
    config: Annotated[
        Path,
        Parameter(
            name=['--config', '-c'],
            help='Path to the repolish YAML configuration file',
        ),
    ] = _DEFAULT_CONFIG,
) -> None:
    """Link provider resources to the project."""
    run_cli_command(lambda: command(config))
