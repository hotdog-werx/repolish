"""Decorator for creating library resource linking CLIs."""

import argparse
import inspect
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hotlog import (
    add_verbosity_argument,
    configure_logging,
    get_logger,
    resolve_verbosity,
)
from rich.console import Console

from repolish.config.models import ProviderInfo, ProviderSymlink
from repolish.exceptions import ResourceLinkerError
from repolish.linker.symlinks import link_resources

logger = get_logger(__name__)

# Create Console with auto-detection: disable colors during tests
# (similar to hotlog's get_console behavior)
_force_terminal = True
if 'pytest' in sys.modules or any(key.startswith('PYTEST_') for key in os.environ):
    _force_terminal = False

console = Console(force_terminal=_force_terminal)


@dataclass
class Symlink:
    """A symlink from provider resources to the project.

    Simple dataclass for the decorator API. Accepts strings for paths.
    """

    source: str
    target: str


def _auto_detect_library_name(caller_frame: inspect.FrameInfo) -> str:
    """Auto-detect library name from the caller's package.

    Converts package name to library name by replacing underscores with dashes
    (Python packages use _, but repo/project names conventionally use -).

    Args:
        caller_frame: Frame info of the caller

    Returns:
        Library name derived from package name

    Raises:
        ResourceLinkerError: If library name cannot be determined
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

    package_name = caller_module.__package__
    if package_name:  # pragma: no cover
        # Use the top-level package name, converting underscores to dashes
        return package_name.split('.')[0].replace('_', '-')

    # This fallback is nearly impossible to trigger - a module with __package__ attribute
    # set to None/empty is not a standard Python module scenario that developers can control.
    msg = 'Could not determine library name: caller module has no package'  # pragma: no cover
    raise ResourceLinkerError(msg)  # pragma: no cover


def _create_argument_parser(
    library_name: str,
    resolved_source_dir: Path,
    default_target_base_path: Path,
) -> argparse.ArgumentParser:
    """Create and configure the argument parser for the resource linker CLI.

    Args:
        library_name: Name of the library
        resolved_source_dir: Resolved path to source directory
        default_target_base_path: Base path for target directory

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        description=f'Link {library_name} resources to your project.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # add standard verbosity switch provided by hotlog
    add_verbosity_argument(parser)

    parser.add_argument(
        '--source-dir',
        type=Path,
        default=resolved_source_dir,
        help=f'Source directory containing {library_name} resources (default: {resolved_source_dir})',
    )

    parser.add_argument(
        '--target-dir',
        type=Path,
        default=default_target_base_path / library_name,
        help=f'Target directory for linked resources (default: {default_target_base_path}/{library_name})',
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force recreation even if target already exists and is correct',
    )

    parser.add_argument(
        '--info',
        action='store_true',
        help='Output JSON with source/target information instead of linking',
    )

    return parser


def _get_package_root(caller_frame: inspect.FrameInfo) -> Path:
    """Get the root directory of the package containing the caller."""
    # Get the module where the decorator was called
    caller_module = inspect.getmodule(caller_frame.frame)
    if (
        caller_module is None or not hasattr(caller_module, '__file__') or caller_module.__file__ is None
    ):  # pragma: no cover - Edge case: module without __file__ (e.g., built-ins, interactive REPL)
        msg = 'Could not determine package root from caller module'
        raise ResourceLinkerError(msg)

    caller_file = Path(caller_module.__file__).resolve()

    # Get the package name (top-level package)
    package_name = caller_module.__package__
    if package_name:
        # Split on '.' to get the top-level package
        top_level_package = package_name.split('.')[0]
    else:  # pragma: no cover - Fallback for standalone modules not in a package
        # If no package, use the module's parent directory
        return caller_file.parent

    # Walk up from the caller's file until we find the package root
    # The package root is the directory containing the top-level package
    current = caller_file.parent
    while current.name != top_level_package and current.parent != current:
        current = current.parent

    # Return the package root (the directory itself, not its parent)
    return current


def resource_linker(
    *,
    library_name: str | None = None,
    default_source_dir: str = 'resources',
    default_target_base: str = '.repolish',
    templates_subdir: str = 'templates',
    default_symlinks: list[Symlink] | None = None,
    _caller_frame: inspect.FrameInfo | None = None,
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
        templates_subdir: Subdirectory within resources containing templates (default: templates)
        default_symlinks: List of Symlink objects defining default symlinks from provider resources.
            Users can override these in their repolish.yaml config by setting symlinks to [] or a custom list.

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
    package_root = _get_package_root(caller_frame)

    # Auto-compute library_name if not provided
    if library_name is None:
        library_name = _auto_detect_library_name(caller_frame)

    # Resolve source dir relative to package root
    # Convert to Path to handle both forward slashes (Unix) and backslashes (Windows)
    resolved_source_dir = package_root / Path(default_source_dir)
    default_target_base_path = Path(default_target_base)

    def decorator(func: Callable) -> Callable:
        def wrapper() -> None:
            parser = _create_argument_parser(
                library_name,
                resolved_source_dir,
                default_target_base_path,
            )
            args = parser.parse_args()
            # Configure logging using resolved verbosity (supports CI auto-detection)
            verbosity = resolve_verbosity(args)
            configure_logging(verbosity=verbosity)

            # If --info mode, output JSON and exit
            if args.info:
                # Create ProviderInfo model and output as JSON
                # Note: target_dir uses absolute() not resolve() to avoid following symlinks
                # Convert Symlink to ProviderSymlink
                provider_symlinks = [
                    ProviderSymlink(
                        source=Path(s.source),
                        target=Path(s.target),
                    )
                    for s in (default_symlinks or [])
                ]
                info = ProviderInfo(
                    target_dir=str(args.target_dir.absolute()),
                    source_dir=str(args.source_dir.absolute()),
                    templates_dir=templates_subdir,
                    library_name=library_name,
                    symlinks=provider_symlinks,
                )
                print(json.dumps(info.model_dump(mode='json'), indent=2))  # noqa: T201 - Allow print for CLI output
                return

            try:
                is_symlink = link_resources(
                    source_dir=args.source_dir,
                    target_dir=args.target_dir,
                    force=args.force,
                )

                link_type = 'symlink' if is_symlink else 'copy'
                logger.info(
                    'resources_linked',
                    library_name=library_name,
                    link_type=link_type,
                    target=str(args.target_dir),
                    _display_level=1,
                )

                # Call the wrapped function (for custom messages or actions)
                func()

            except Exception as e:
                logger.exception('linking_failed', error=str(e))
                sys.exit(1)

        return wrapper

    return decorator


def resource_linker_cli(
    *,
    library_name: str | None = None,
    default_source_dir: str = 'resources',
    default_target_base: str = '.repolish',
    templates_subdir: str = 'templates',
    default_symlinks: list[Symlink] | None = None,
) -> Callable[[], None]:
    """Create a resource linker CLI function.

    This is a simpler alternative to the @resource_linker decorator.
    Just assign it to `main` and register it in your pyproject.toml.

    Args:
        library_name: Name of the library (used for default target subdirectory).
            If not provided, auto-detects from the caller's top-level package name.
        default_source_dir: Path to resources relative to package root (default: 'resources').
        default_target_base: Default base directory for the target (default: .repolish)
        templates_subdir: Subdirectory within resources containing templates (default: templates)
        default_symlinks: List of Symlink objects defining default symlinks from provider resources.
            Users can override these in their repolish.yaml config by setting symlinks to [] or a custom list.

    Returns:
        A callable that runs the resource linking CLI

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

    # Determine library name early
    detected_library_name = _auto_detect_library_name(caller_frame) if library_name is None else library_name

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
        templates_subdir=templates_subdir,
        default_symlinks=default_symlinks,
        _caller_frame=caller_frame,
    )

    # Get the wrapped function and return it
    return decorator_factory(_success_message)
