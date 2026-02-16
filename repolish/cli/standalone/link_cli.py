from pathlib import Path

import typer
from hotlog import get_logger, verbosity_option

from repolish.cli.link import CONFIG_OPTION, link
from repolish.cli.utils import setup_logging

logger = get_logger(__name__)

# Create standalone Typer app for repolish-link
app = typer.Typer()


@app.command()
def link_cmd(
    config: Path = CONFIG_OPTION,
    verbose: int = verbosity_option,
) -> None:
    """Link provider resources to the project."""
    # Set up logging early
    setup_logging(verbose)

    # Deprecation warning
    logger.warning(
        'repolish_link_deprecated',
        message='repolish-link is deprecated. Use "repolish link" instead.',
    )

    # Call the shared link function
    link(config)


if __name__ == '__main__':
    app()
