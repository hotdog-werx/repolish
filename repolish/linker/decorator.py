"""Decorator for creating library resource linking CLIs."""

import argparse
import inspect
import json
import sys
from collections.abc import Callable
from pathlib import Path

from hotlog import (
    add_verbosity_argument,
    configure_logging,
    get_logger,
    resolve_verbosity,
)

from repolish.config.models import ProviderInfo

from .symlinks import link_resources

logger = get_logger(__name__)


def _get_package_root(caller_frame: inspect.FrameInfo) -> Path:
    """Get the root directory of the package containing the caller."""
    # Get the module where the decorator was called
    caller_module = inspect.getmodule(caller_frame.frame)
    if (
        caller_module is None or not hasattr(caller_module, '__file__') or caller_module.__file__ is None
    ):  # pragma: no cover - Edge case: module without __file__ (e.g., built-ins, interactive REPL)
        msg = 'Could not determine package root from caller module'
        raise ValueError(msg)

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
    library_name: str,
    default_source_dir: str,
    default_target_base: str = '.repolish',
    templates_subdir: str = 'templates',
) -> Callable:
    """Decorator to create a CLI for linking library resources.

    This decorator wraps a function to create a simple CLI that links
    a library's resource directory to a target location.

    Args:
        library_name: Name of the library (used for default target subdirectory)
        default_source_dir: Path to resources relative to package root (e.g., 'resources' or 'mylib/templates')
        default_target_base: Default base directory for the target (default: .repolish)
        templates_subdir: Subdirectory within resources containing templates (default: templates)

    Example:
        ```python
        from pkglink.repolish import resource_linker

        @resource_linker(
            library_name='mylib',
            default_source_dir='resources',
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
    caller_frame = inspect.stack()[1]
    package_root = _get_package_root(caller_frame)

    # Resolve source dir relative to package root
    # Convert to Path to handle both forward slashes (Unix) and backslashes (Windows)
    resolved_source_dir = package_root / Path(default_source_dir)
    default_target_base_path = Path(default_target_base)

    def decorator(func: Callable) -> Callable:
        def wrapper() -> None:
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
                help='Force recreation even if target exists and is up-to-date',
            )

            parser.add_argument(
                '--info',
                action='store_true',
                help='Output JSON with source/target information instead of linking',
            )

            args = parser.parse_args()
            # Configure logging using resolved verbosity (supports CI auto-detection)
            verbosity = resolve_verbosity(args)
            configure_logging(verbosity=verbosity)

            # If --info mode, output JSON and exit
            if args.info:
                # Create ProviderInfo model and output as JSON
                # Note: target_dir uses absolute() not resolve() to avoid following symlinks
                info = ProviderInfo(
                    target_dir=str(args.target_dir.absolute()),
                    source_dir=str(args.source_dir.absolute()),
                    templates_dir=templates_subdir,
                    library_name=library_name,
                )
                print(json.dumps(info.model_dump(), indent=2))  # noqa: T201 - Allow print for CLI output
                return

            try:
                logger.info(
                    'linking_resources',
                    library_name=library_name,
                    source=str(args.source_dir),
                    target=str(args.target_dir),
                    _display_level=1,
                )

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

                # Call the wrapped function
                func()

            except Exception as e:
                logger.exception('linking_failed', error=str(e))
                sys.exit(1)

        return wrapper

    return decorator
