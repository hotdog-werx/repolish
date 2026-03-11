from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger

from repolish.cli.utils import run_cli_command
from repolish.scaffold import generate

logger = get_logger(__name__)


def scaffold(
    name: str,
    *,
    output_dir: Annotated[
        Path,
        Parameter(name=['--output-dir', '-o']),
    ] = Path(),
) -> None:
    """Scaffold a new repolish provider package.

    NAME is the provider/repo name (e.g. 'codeguide-workspace').
    Package name and class name are derived automatically.
    Existing files are never overwritten.
    """

    def _run() -> int:
        dest = output_dir.resolve()
        written = generate(name, dest)
        if not written:
            logger.info(
                'scaffold: nothing to write — all files already exist',
                dest=str(dest),
            )
            return 0
        for path in written:
            logger.info('scaffold: created', path=str(path.relative_to(dest)))
        logger.info('scaffold: done', count=len(written), dest=str(dest))
        return 0

    run_cli_command(_run)
