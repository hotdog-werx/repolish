from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger

from repolish.cli.utils import run_cli_command
from repolish.commands.preview import command

logger = get_logger(__name__)


def preview(
    debug_file: Annotated[
        Path,
        Parameter(help='Path to the YAML debug configuration file'),
    ],
    *,
    show_patterns: Annotated[
        bool,
        Parameter(help='Show extracted patterns from template'),
    ] = False,
    show_steps: Annotated[
        bool,
        Parameter(help='Show intermediate processing steps'),
    ] = False,
) -> None:
    """Preview/test templates."""
    run_cli_command(
        lambda: command(
            debug_file,
            show_patterns=show_patterns,
            show_steps=show_steps,
        ),
    )
