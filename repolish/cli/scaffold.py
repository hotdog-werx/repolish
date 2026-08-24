from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger

from repolish.cli.utils import run_cli_command
from repolish.console import console

logger = get_logger(__name__)


def _report_written(written: list[Path], cwd: Path, dest: Path) -> None:
    """Log the scaffold result, listing created files relative to the cwd."""
    if not written:
        logger.info(
            'scaffold: nothing to write — all files already exist',
            dest=str(dest),
        )
        return
    for path in written:
        try:
            rel = path.relative_to(cwd)
        except ValueError:
            rel = path
        logger.info('scaffold: created', path=str(rel))
    logger.info('scaffold: done', count=len(written), dest=str(dest))


def _run_local(directory: Path, dest: Path, prefix: str | None) -> None:
    """Scaffold an in-repo local provider into *dest*."""
    # Deferred so that importing this CLI module does not eagerly load the
    # scaffold package when a different subcommand is invoked.
    from repolish.scaffold import generate_local  # noqa: PLC0415

    alias = directory.name.replace('-', '_') or 'local'
    # provider_root hint uses the directory as the user typed it
    provider_root = (directory / 'templates').as_posix()
    written = generate_local(
        alias,
        dest,
        provider_root=provider_root,
        prefix=prefix,
    )
    _report_written(written, Path.cwd(), dest)
    if written:
        console.print('[bold]add the provider to repolish.yaml:[/bold]')
        console.print(
            f'providers:\n  {alias}:\n    provider_root: {provider_root}',
            style='cyan',
        )


def _run_package(
    package: str | None,
    dest: Path,
    prefix: str | None,
    *,
    monorepo: bool,
) -> int:
    """Scaffold an installable provider package into *dest*."""
    # Deferred so that importing this CLI module does not eagerly load the
    # scaffold package when a different subcommand is invoked.
    from repolish.scaffold import generate  # noqa: PLC0415

    if package is None:
        logger.error('scaffold: --package is required unless --local is given')
        return 1
    written = generate(package, dest, prefix, simple=not monorepo)
    _report_written(written, Path.cwd(), dest)
    return 0


def scaffold(
    directory: Annotated[
        Path,
        Parameter(help='Destination directory (created if it does not exist).'),
    ],
    *,
    package: Annotated[
        str | None,
        Parameter(
            name=['--package', '-p'],
            help=(
                'Python package name. '
                'Use a simple name for flat packages (e.g. devkit_workspace) '
                'or dot-notation for namespace packages (e.g. devkit.workspace). '
                'Required unless --local is given.'
            ),
        ),
    ] = None,
    prefix: Annotated[
        str | None,
        Parameter(
            name=['--prefix'],
            help=(
                'Class-name prefix override (defaults to the last segment of '
                '--package, or the alias camel-cased with --local).'
            ),
        ),
    ] = None,
    monorepo: Annotated[
        bool,
        Parameter(
            name=['--monorepo'],
            help=(
                'Generate the full monorepo provider layout with root, member, '
                'and standalone mode handlers. By default a simpler single-file '
                'provider is generated.'
            ),
        ),
    ] = False,
    local: Annotated[
        bool,
        Parameter(
            name=['--local'],
            help=(
                'Generate an in-repo local provider instead of an installable '
                'package: DIRECTORY/templates/repolish.py plus a repolish/ '
                'template directory. Connect it in repolish.yaml with only '
                'provider_root — no CLI, no publishing step.'
            ),
        ),
    ] = False,
) -> None:
    """Scaffold a new repolish provider.

    DIRECTORY is where the provider will be placed.  With --local it holds the
    provider's templates directly; otherwise it receives pyproject.toml,
    README.md, repolish.yaml and the package directory.  Use '.' for the
    current directory.  Existing files are never overwritten.
    """

    def _run() -> int:
        dest = (Path.cwd() / directory).resolve()

        if local:
            if package is not None:
                logger.error(
                    'scaffold: --package has no effect with --local (local providers are not packages)',
                )
                return 1
            if monorepo:
                logger.error(
                    'scaffold: --monorepo cannot be combined with --local',
                )
                return 1
            _run_local(directory, dest, prefix)
            return 0

        return _run_package(package, dest, prefix, monorepo=monorepo)

    run_cli_command(_run)
