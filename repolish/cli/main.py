import typer
from hotlog import verbosity_option

from repolish.cli.apply import apply
from repolish.cli.link import link
from repolish.cli.lint import lint
from repolish.cli.preview import preview
from repolish.cli.utils import setup_logging
from repolish.version import __version__

app = typer.Typer()

# Module-level constants for Typer options to avoid B008
VERSION_OPTION = typer.Option(
    default=False,
    help='Show version and exit',
)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    *,
    verbose: int = verbosity_option,
    version: bool = VERSION_OPTION,
) -> None:
    """Repolish - Maintain consistency across repositories."""
    if version:
        typer.echo(__version__)
        raise typer.Exit(0)

    setup_logging(verbose)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


# Add subcommands to the main app
app.command()(apply)
app.command()(preview)
app.command()(link)
app.command()(lint)
