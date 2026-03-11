from pathlib import Path
from typing import Annotated

from cyclopts import Parameter

from repolish.cli.utils import run_cli_command
from repolish.commands.apply import command

_DEFAULT_CONFIG = Path('repolish.yaml')


def apply(
    config: Annotated[
        Path,
        Parameter(
            name=['--config', '-c'],
            help='Path to the repolish YAML configuration file',
        ),
    ] = _DEFAULT_CONFIG,
    *,
    check: Annotated[
        bool,
        Parameter(help='Load config and create context (dry-run check)'),
    ] = False,
) -> None:
    """Apply templates to project."""
    run_cli_command(lambda: command(config, check_only=check))
