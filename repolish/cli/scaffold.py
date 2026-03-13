from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger

from repolish.cli.utils import run_cli_command
from repolish.scaffold import generate

logger = get_logger(__name__)


def scaffold(
    directory: Annotated[
        Path,
        Parameter(help='Destination directory (created if it does not exist).'),
    ],
    *,
    package: Annotated[
        str,
        Parameter(name=['--package', '-p'], help='Python package name, e.g. codeguide_workspace.'),
    ],
    prefix: Annotated[
        str | None,
        Parameter(
            name=['--prefix'],
            help='Class-name prefix override (defaults to the last segment of --package).',
        ),
    ] = None,
) -> None:
    """Scaffold a new repolish provider package.

    DIRECTORY is where pyproject.toml, README.md, repolish.yaml and the
    package directory will be placed.  Use '.' for the current directory.
    Existing files are never overwritten.
    """

    def _run() -> int:
        cwd = Path.cwd()
        dest = (cwd / directory).resolve()
        written = generate(package, dest, prefix)
        if not written:
            logger.info(
                'scaffold: nothing to write — all files already exist',
                dest=str(dest),
            )
            return 0
        for path in written:
            try:
                rel = path.relative_to(cwd)
            except ValueError:
                rel = path
            logger.info('scaffold: created', path=str(rel))
        logger.info('scaffold: done', count=len(written), dest=str(dest))
        return 0

    run_cli_command(_run)
