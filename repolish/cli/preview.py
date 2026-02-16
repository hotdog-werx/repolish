from pathlib import Path

import typer
from hotlog import get_logger

from repolish.cli.utils import run_cli_command
from repolish.commands.preview import command

logger = get_logger(__name__)

# Module-level constants for Typer options to avoid B008
DEBUG_FILE_ARG = typer.Argument(
    ...,
    help='Path to the YAML debug configuration file',
)
SHOW_PATTERNS_OPTION = typer.Option(
    default=False,
    help='Show extracted patterns from template',
)
SHOW_STEPS_OPTION = typer.Option(
    default=False,
    help='Show intermediate processing steps',
)


def preview(
    debug_file: Path = DEBUG_FILE_ARG,
    *,
    show_patterns: bool = SHOW_PATTERNS_OPTION,
    show_steps: bool = SHOW_STEPS_OPTION,
) -> None:
    """Preview/test templates."""
    # Logging is already configured by setup_logging in CLI entry points
    run_cli_command(
        lambda: command(
            debug_file,
            show_patterns=show_patterns,
            show_steps=show_steps,
        ),
    )
