from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from hotlog import get_logger
from pydantic import BaseModel, Field

from repolish.cli.utils import run_cli_command
from repolish.console import console

logger = get_logger(__name__)


@Parameter(name='*')
class ScaffoldParams(BaseModel):
    """Parameters for the scaffold command."""

    directory: Annotated[
        Path | None,
        Parameter(name='DIRECTORY'),
    ] = Field(
        default=None,
        description=(
            'Destination directory (created if it does not exist). '
            'Defaults to internal/ with --local; required otherwise.'
        ),
    )
    package: Annotated[
        str | None,
        Parameter(name=['--package', '-p']),
    ] = Field(
        default=None,
        description=(
            'Python package name. Use a simple name for flat packages (e.g. devkit_workspace) '
            'or dot-notation for namespace packages (e.g. devkit.workspace). '
            'Required unless --local is given.'
        ),
    )
    prefix: str | None = Field(
        default=None,
        description=(
            'Class-name prefix override (defaults to the last segment of '
            '--package, or the alias camel-cased with --local).'
        ),
    )
    monorepo: bool = Field(
        default=False,
        description=(
            'Generate the full monorepo provider layout with root, member, '
            'and standalone mode handlers. By default a simpler single-file '
            'provider is generated.'
        ),
    )
    local: bool = Field(
        default=False,
        description=(
            'Generate an in-repo local provider instead of an installable '
            'package: internal/templates/repolish.py plus a repolish/ '
            'template directory, aliased "local" and wired up in '
            'repolish.yaml with only provider_root — no CLI, no package '
            'name, no publishing step.'
        ),
    )
    installable: bool = Field(
        default=False,
        description=(
            'Only meaningful with --local: scaffold the installable tier — '
            'pyproject.toml plus an internal/ package holding the real '
            'provider code, with templates/repolish.py reduced to a shim. '
            'Needed once the provider wants sibling-module imports.'
        ),
    )


_DEFAULT_SCAFFOLD_PARAMS = ScaffoldParams()


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


def _run_local(params: ScaffoldParams) -> None:
    """Scaffold an in-repo local provider.

    By convention the provider lives under ``internal/`` (sibling to ``src/``)
    and is aliased ``local`` in repolish.yaml — ``params.directory`` only
    overrides the location, never the provider identity.
    """
    # Deferred so that importing this CLI module does not eagerly load the
    # scaffold package when a different subcommand is invoked.
    from repolish.scaffold import generate_local  # noqa: PLC0415
    from repolish.scaffold.generator import (  # noqa: PLC0415
        LOCAL_PROVIDER_ALIAS,
        LOCAL_PROVIDER_DIR,
    )

    directory = params.directory or Path(LOCAL_PROVIDER_DIR)
    dest = (Path.cwd() / directory).resolve()
    # hints display the directory relative to the cwd when possible
    try:
        display = dest.relative_to(Path.cwd())
    except ValueError:  # pragma: no cover - dest is always cwd-relative in tests
        display = directory
    provider_root = (display / 'templates').as_posix()
    written = generate_local(
        LOCAL_PROVIDER_ALIAS,
        dest,
        provider_root=provider_root,
        prefix=params.prefix,
        installable=params.installable,
    )
    _report_written(written, Path.cwd(), dest)
    if not written:  # pragma: no cover - no files written, nothing to report
        return
    console.print('[bold]add the provider to repolish.yaml:[/bold]')
    console.print(
        f'providers:\n  {LOCAL_PROVIDER_ALIAS}:\n    provider_root: {provider_root}',
        style='cyan',
    )
    if params.installable:
        console.print(
            f'[bold]editable-install [cyan]{display}[/cyan] into the environment that '
            f'runs repolish[/bold] (e.g. [cyan]-e ./{display}[/cyan] in its requirements)',
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


def _validate(params: ScaffoldParams) -> str | None:
    """Return an error message when the option combination is invalid."""
    if params.local:
        if params.package is not None:
            return '--package has no effect with --local (local providers are not packages)'
        if params.monorepo:
            return '--monorepo cannot be combined with --local'
        return None
    if params.installable:
        return '--installable requires --local'
    if params.directory is None:
        return 'DIRECTORY is required unless --local is given'
    return None


def _run(params: ScaffoldParams) -> int:
    """Validate the option combination, then dispatch to the local or package scaffold."""
    if error := _validate(params):
        logger.error('scaffold: invalid option combination', reason=error)
        return 1
    if params.local:
        _run_local(params)
        return 0
    # unreachable: rejected by _validate
    if params.directory is None:  # pragma: no cover
        return 1
    dest = (Path.cwd() / params.directory).resolve()
    return _run_package(params.package, dest, params.prefix, monorepo=params.monorepo)


def scaffold(params: ScaffoldParams = _DEFAULT_SCAFFOLD_PARAMS) -> None:
    """Scaffold a new repolish provider.

    DIRECTORY is where the provider will be placed.  With --local it defaults
    to internal/ (the repo-maintenance location, sibling to src/) and holds the
    provider's templates directly; otherwise it receives pyproject.toml,
    README.md, repolish.yaml and the package directory.  Use '.' for the
    current directory.  Existing files are never overwritten.
    """
    run_cli_command(lambda: _run(params))
