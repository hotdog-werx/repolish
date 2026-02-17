from collections.abc import Callable

import typer
from hotlog import configure_logging, resolve_verbosity


def setup_logging(verbose: int) -> None:
    """Set up logging configuration for CLI commands.

    Args:
        verbose: Verbosity level (0=normal, 1=verbose, 2=debug)
    """
    verbosity = resolve_verbosity(verbose=verbose)
    configure_logging(verbosity=verbosity)


def run_cli_command(func: Callable[[], int]) -> None:
    """Execute a CLI command function with proper exception handling.

    This is a convenience function for running CLI commands that return exit codes.
    Any exception will bubble up so Typer shows the full traceback, successful execution will result
    in typer.Exit(exit_code).

    Args:
        func: A callable that takes no arguments and returns an exit code (int)
    """
    exit_code = func()
    raise typer.Exit(exit_code)
