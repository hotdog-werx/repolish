from pathlib import Path

import typer
from hotlog import get_logger, verbosity_option

from repolish.cli.apply import apply
from repolish.cli.link import link
from repolish.cli.preview import preview
from repolish.cli.utils import run_cli_command, setup_logging
from repolish.commands import apply_cmd
from repolish.version import __version__

logger = get_logger(__name__)

app = typer.Typer()

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
VERSION_OPTION = typer.Option(
    default=False,
    help='Show version and exit',
)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    *,
    config: Path = CONFIG_OPTION,
    check: bool = CHECK_OPTION,
    verbose: int = verbosity_option,
    version: bool = VERSION_OPTION,
) -> None:
    """Repolish - Maintain consistency across repositories."""
    if version:
        typer.echo(__version__)
        raise typer.Exit(0)

    # Always set up logging for both main command and subcommands
    setup_logging(verbose)

    if ctx.invoked_subcommand is None:
        # Run main repolish functionality when no subcommand is specified
        logger.warning(
            'bare_repolish_deprecated',
            message='Using "repolish" without a subcommand is deprecated. Use "repolish apply" instead.',
        )
        run_cli_command(lambda: apply_cmd(config, check_only=check))


# Add subcommands to the main app
app.command()(apply)
app.command()(preview)
app.command()(link)
