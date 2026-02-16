from pathlib import Path

import typer
from hotlog import get_logger, verbosity_option

from repolish.cli.preview import (
    DEBUG_FILE_ARG,
    SHOW_PATTERNS_OPTION,
    SHOW_STEPS_OPTION,
    preview,
)
from repolish.cli.utils import setup_logging

logger = get_logger(__name__)

# Create standalone Typer app for repolish-debugger
app = typer.Typer()


@app.command()
def debug(
    debug_file: Path = DEBUG_FILE_ARG,
    *,
    show_patterns: bool = SHOW_PATTERNS_OPTION,
    show_steps: bool = SHOW_STEPS_OPTION,
    verbose: int = verbosity_option,
) -> None:
    """Debug preprocessor tool for repolish."""
    setup_logging(verbose)
    logger.warning(
        'repolish_debugger_deprecated',
        message='repolish-debugger is deprecated. Use "repolish preview" instead.',
    )
    preview(debug_file, show_patterns=show_patterns, show_steps=show_steps)


if __name__ == '__main__':
    app()
