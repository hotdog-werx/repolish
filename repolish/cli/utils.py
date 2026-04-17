from collections.abc import Callable

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

    Any exception will bubble up so the CLI shows the full traceback.
    A non-zero exit code is surfaced via :class:`SystemExit`.

    Args:
        func: A callable that takes no arguments and returns an exit code (int)
    """
    exit_code = func()
    if exit_code:
        raise SystemExit(exit_code)
