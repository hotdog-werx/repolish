"""Decorator for creating library resource linking CLIs."""

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated

import cyclopts
from cyclopts import Parameter
from hotlog import (
    configure_logging,
    get_logger,
    resolve_verbosity,
)

from repolish.config import ProviderInfo, ProviderSymlink
from repolish.console import console
from repolish.exceptions import ResourceLinkerError
from repolish.linker.symlinks import link_resources
from repolish.pkginfo import resolve_package_identity

logger = get_logger(__name__)


@dataclass
class Symlink:
    """A symlink from provider resources to the project.

    Simple dataclass for the decorator API. Accepts strings for paths.
    """

    source: str
    target: str


def _auto_detect_library_name(
    caller_frame: inspect.FrameInfo,
) -> tuple[str, str, str]:
    """Resolve package identity from the caller's frame.

    Uses :func:`repolish.pkginfo.resolve_package_identity` to derive the
    canonical module name and distribution name from the caller's
    ``__package__`` attribute.

    Args:
        caller_frame: Frame info of the caller

    Returns:
        ``(package_attr, pkg, project)`` where *package_attr* is the raw
        ``__package__`` value, *pkg* is the canonical module name, and
        *project* is the distribution name (may be ``''`` if unresolvable).

    Raises:
        ResourceLinkerError: If the caller module or its package cannot be
            determined.
    """
    caller_module = inspect.getmodule(caller_frame.frame)
    if caller_module is None or not hasattr(
        caller_module,
        '__package__',
    ):  # pragma: no cover
        # This edge case is difficult to test in practice - requires calling from a context
        # where inspect.getmodule() returns None or a module without __package__ attribute.
        # Real-world usage from properly structured Python packages will not hit this path.
        msg = 'Could not determine library name from caller module'
        raise ResourceLinkerError(msg)

    package_attr = caller_module.__package__
    if not package_attr:  # pragma: no cover
        msg = 'Could not determine library name: caller module has no package'
        raise ResourceLinkerError(msg)

    pkg, project = resolve_package_identity(package_attr)
    return package_attr, pkg, project


def _get_package_root(module_name: str, caller_file: Path) -> Path:
    """Return the directory that is the package root for *module_name*.

    Uses :func:`importlib.util.find_spec` on the fully-resolved *module_name*
    (as returned by :func:`~repolish.pkginfo.resolve_package_identity`) so
    that both flat packages and namespace packages are handled correctly:

    - Flat package ``devkit_zensical``:  spec points at ``devkit_zensical/``.
    - Namespace package ``devkit.zensical``: spec points at
      ``devkit/zensical/``, not the namespace root ``devkit/``.

    Falls back to *caller_file*'s parent when the spec cannot be resolved
    (e.g. standalone module not installed in the environment).

    Args:
        module_name: Canonical dotted module name from ``resolve_package_identity``.
        caller_file: Resolved path of the calling module's ``__file__``,
            used as a fallback when *module_name* cannot be found via
            ``find_spec``.
    """
    if module_name:
        spec = find_spec(module_name)
        if spec and spec.submodule_search_locations:
            return Path(next(iter(spec.submodule_search_locations))).resolve()
    return caller_file.parent


def _build_provider_info(  # noqa: PLR0913 - many parameters are needed to construct the ProviderInfo
    target_dir: Path,
    source_dir: Path,
    library_name: str,
    templates_dir: str,
    pkg_name: str,
    proj_name: str,
    default_symlinks: list[Symlink] | None,
) -> ProviderInfo:
    """Construct the ProviderInfo object emitted by the ``--info`` flag."""
    provider_symlinks = [
        ProviderSymlink(source=Path(s.source), target=Path(s.target)) for s in (default_symlinks or [])
    ]
    return ProviderInfo(
        target_dir=str(target_dir.absolute()),
        source_dir=str(source_dir.absolute()),
        library_name=library_name,
        templates_dir=templates_dir,
        package_name=pkg_name,
        project_name=proj_name,
        symlinks=provider_symlinks,
    )


def _link_and_notify(
    source_dir: Path,
    target_dir: Path,
    *,
    force: bool,
    library_name: str,
    func: Callable,
) -> None:
    """Run link_resources and call the success callback, or raise SystemExit on failure."""
    try:
        is_symlink = link_resources(
            source_dir=source_dir,
            target_dir=target_dir,
            force=force,
        )
        link_type = 'symlink' if is_symlink else 'copy'
        logger.info(
            'resources_linked',
            library_name=library_name,
            link_type=link_type,
            target=str(target_dir),
            _display_level=1,
        )
        func()
    except Exception as e:
        logger.exception('linking_failed', error=str(e))
        raise SystemExit(1) from None


def resource_linker(
    *,
    library_name: str | None = None,
    default_source_dir: str = 'resources',
    default_target_base: str = '.repolish',
    default_symlinks: list[Symlink] | None = None,
    templates_dir: str = '',
    _caller_frame: inspect.FrameInfo | None = None,
    _pkg_name: str = '',
    _proj_name: str = '',
) -> Callable:
    """Decorator to create a CLI for linking library resources.

    This decorator wraps a function to create a simple CLI that links
    a library's resource directory to a target location.

    Args:
        library_name: Name of the library (used for default target subdirectory).
            If not provided, auto-detects from the caller's top-level package name.
        default_source_dir: Path to resources relative to package root (default: 'resources').
            Can be overridden for custom locations (e.g., 'mylib/templates').
        default_target_base: Default base directory for the target (default: .repolish)
        default_symlinks: List of Symlink objects defining default symlinks from provider resources.
            Users can override these in their repolish.yaml config by setting symlinks to [] or a custom list.
        templates_dir: Subdirectory within source_dir where repolish.py and templates live.
            Recorded in provider-info JSON so the loader resolves the correct templates root.
            Defaults to empty string (repolish.py sits directly in source_dir).
        _caller_frame: Internal — caller frame injected by :func:`resource_linker_cli`.
        _pkg_name: Internal — pre-resolved module name; skips :func:`resolve_package_identity`
            when provided by :func:`resource_linker_cli`.
        _proj_name: Internal — pre-resolved distribution name; same as above.

    Example:
        ```python
        from repolish.linker import resource_linker, Symlink

        # Minimal usage - auto-detects library name from package
        @resource_linker()
        def main():
            print("Resources linked successfully!")

        # With default symlinks
        @resource_linker(
            library_name='custom-name',
            default_source_dir='templates',
            default_symlinks=[
                Symlink(source='configs/.editorconfig', target='.editorconfig'),
                Symlink(source='configs/.gitignore', target='.gitignore'),
            ],
        )
        def main():
            print("Resources linked successfully!")

        if __name__ == '__main__':
            main()
        ```

    This creates a CLI with the following arguments:
        --source-dir: Override the source directory
        --target-dir: Override the target directory (defaults to .repolish/library-name)
        --force: Force recreation even if target exists and is up-to-date
    """
    # Get caller's frame to determine package root
    # Use provided frame (from resource_linker_cli) or inspect the stack
    caller_frame = _caller_frame if _caller_frame is not None else inspect.stack()[1]

    # Resolve package identity once; use it for both the package root and
    # the library name so resolve_package_identity is not called twice.
    # When called from resource_linker_cli, _pkg_name/_proj_name are already
    # resolved and forwarded here to avoid a second lookup.
    caller_module = inspect.getmodule(caller_frame.frame)
    _caller_file = Path(getattr(caller_module, '__file__', '') or '').resolve()
    if not _pkg_name:
        _package_attr = getattr(caller_module, '__package__', '') or ''
        _pkg_name, _proj_name = resolve_package_identity(_package_attr)
    package_root = _get_package_root(_pkg_name, _caller_file)
    library_name = library_name or _proj_name or _pkg_name.replace('_', '-')

    resolved_source_dir = package_root / Path(default_source_dir)
    default_target_base_path = Path(default_target_base)

    def decorator(func: Callable) -> cyclopts.App:
        link_app = cyclopts.App(
            help=f'Link {library_name} resources to your project.',
        )

        @link_app.default
        def _command(
            *,
            source_dir: Annotated[
                Path,
                Parameter(
                    help=f'Source directory containing {library_name} resources (default: {resolved_source_dir})',
                ),
            ] = resolved_source_dir,
            target_dir: Annotated[
                Path,
                Parameter(
                    help=f'Target directory for linked resources (default: {default_target_base_path}/{library_name})',
                ),
            ] = default_target_base_path / library_name,
            force: Annotated[
                bool,
                Parameter(
                    help='Force recreation even if target already exists and is correct',
                ),
            ] = False,
            info: Annotated[
                bool,
                Parameter(
                    help='Output JSON with source/target information instead of linking',
                ),
            ] = False,
            verbose: Annotated[
                int,
                Parameter(name=['-v', '--verbose'], count=True),
            ] = 0,
        ) -> None:
            configure_logging(verbosity=resolve_verbosity(verbose=verbose))
            if info:
                info_obj = _build_provider_info(
                    target_dir,
                    source_dir,
                    library_name,
                    templates_dir,
                    _pkg_name,
                    _proj_name,
                    default_symlinks,
                )
                print(json.dumps(info_obj.model_dump(mode='json'), indent=2))  # noqa: T201
            else:
                _link_and_notify(
                    source_dir,
                    target_dir,
                    force=force,
                    library_name=library_name,
                    func=func,
                )

        return link_app

    return decorator


def resource_linker_cli(
    *,
    library_name: str | None = None,
    default_source_dir: str = 'resources',
    default_target_base: str = '.repolish',
    default_symlinks: list[Symlink] | None = None,
    templates_dir: str = 'templates',
) -> cyclopts.App:
    """Create a resource linker CLI function.

    This is a simpler alternative to the @resource_linker decorator.
    Just assign it to `main` and register it in your pyproject.toml.

    Args:
        library_name: Name of the library (used for default target subdirectory).
            If not provided, auto-detects from the caller's top-level package name.
        default_source_dir: Path to resources relative to package root (default: 'resources').
        default_target_base: Default base directory for the target (default: .repolish)
        default_symlinks: List of Symlink objects defining default symlinks from provider resources.
            Users can override these in their repolish.yaml config by setting symlinks to [] or a custom list.
        templates_dir: Subdirectory within source_dir where repolish.py and templates live
            (default: 'templates').  Recorded in provider-info JSON so the loader can locate
            the provider entry point at target_dir/templates_dir/repolish.py.

    Returns:
        A :class:`cyclopts.App` that runs the resource linking CLI.

    Example:
        In your CLI module (e.g., mylib/cli.py):
        ```python
        from repolish.linker import resource_linker_cli, Symlink

        main = resource_linker_cli(
            default_symlinks=[
                Symlink(source='configs/.editorconfig', target='.editorconfig'),
            ],
        )
        ```

        In pyproject.toml:
        ```toml
        [project.scripts]
        mylib-link = "mylib.cli:main"
        ```
    """
    # Get caller's frame for library name detection
    caller_frame = inspect.stack()[1]

    # Resolve package identity early so the success message can use the
    # detected library name before the decorator is applied.
    _, _pkg, _proj = _auto_detect_library_name(caller_frame)
    detected_library_name = library_name or _proj or _pkg.replace('_', '-')

    # Create a function with auto-generated success message
    def _success_message() -> None:
        """Auto-generated success message."""
        console.print(
            f'- [bold cyan]{default_source_dir}[/bold cyan] from '
            f'[bold green]{detected_library_name}[/bold green] are now available',
        )

    # Apply the decorator to create the CLI
    # Pass the caller frame so resource_linker uses the correct package context
    decorator_factory = resource_linker(
        library_name=library_name,
        default_source_dir=default_source_dir,
        default_target_base=default_target_base,
        default_symlinks=default_symlinks,
        templates_dir=templates_dir,
        _caller_frame=caller_frame,
        _pkg_name=_pkg,
        _proj_name=_proj,
    )

    # Get the wrapped function and return it
    return decorator_factory(_success_message)
