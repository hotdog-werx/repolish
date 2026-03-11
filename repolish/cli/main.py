"""Main Repolish CLI application."""

from typing import Annotated

import cyclopts
from cyclopts import Parameter

from repolish.cli.apply import apply
from repolish.cli.link import link
from repolish.cli.lint import lint
from repolish.cli.preview import preview
from repolish.cli.utils import setup_logging
from repolish.version import __version__

app = cyclopts.App(
    name='repolish',
    version=__version__,
    help='Repolish - Maintain consistency across repositories.',
)


@app.meta.default
def _meta(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    verbose: Annotated[
        int,
        Parameter(name=['-v', '--verbose'], count=True, help='Increase verbosity (-v, -vv).'),
    ] = 0,
) -> None:
    """Repolish - Maintain consistency across repositories."""
    setup_logging(verbose)
    app(tokens)


def main() -> None:  # pragma: no cover - real process entry point, not exercised in tests
    """Entry point for the repolish CLI."""
    app.meta()


app.command()(apply)
app.command()(preview)
app.command()(link)
app.command()(lint)
