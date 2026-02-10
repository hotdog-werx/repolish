"""CLI for linking provider resources to the project."""

import argparse
import sys
from pathlib import Path

from hotlog import (
    add_verbosity_argument,
    configure_logging,
    get_logger,
    resolve_verbosity,
)

from .config import load_config_file
from .config.models import RepolishConfigFile
from .exceptions import RepolishError, log_exception
from .linker import process_provider

logger = get_logger(__name__)


def _get_provider_names(config: RepolishConfigFile) -> list[str]:
    """Get list of provider names in the correct order.

    Args:
        config: Raw repolish configuration file

    Returns:
        List of provider names to process (from providers_order or providers dict key order)
    """
    if config.providers_order:
        return config.providers_order
    # If no order specified, use providers dict key order (preserves YAML order)
    return list(config.providers.keys())


def run(argv: list[str]) -> int:
    """Run repolish-link with argv-like list and return an exit code.

    This is separated from `main()` so we can keep `main()` small and
    maintain a low cyclomatic complexity for the top-level entrypoint.
    """
    parser = argparse.ArgumentParser(
        prog='repolish-link',
        description='Link provider resources to the project',
    )
    add_verbosity_argument(parser)
    parser.add_argument(
        '--config',
        dest='config',
        type=Path,
        default=Path('repolish.yaml'),
        help='Path to the repolish YAML configuration file',
    )
    args = parser.parse_args(argv)
    config_path = args.config

    # Configure logging using resolved verbosity (supports CI auto-detection)
    verbosity = resolve_verbosity(args)
    configure_logging(verbosity=verbosity)

    logger.info(
        'loading_config',
        config_file=str(config_path),
        _display_level=1,
    )
    # Load raw config (don't resolve) to access provider CLI commands
    config = load_config_file(config_path)

    if not config.providers:
        logger.warning('no_providers_configured', _display_level=1)
        return 0

    provider_names = _get_provider_names(config)
    logger.info(
        'linking_providers',
        providers=provider_names,
        _display_level=1,
    )

    # Process each provider
    for provider_name in provider_names:
        if provider_name not in config.providers:
            logger.warning(
                'provider_not_found_in_order',
                provider=provider_name,
                _display_level=1,
            )
            continue

        provider_config = config.providers[provider_name]
        exit_code = process_provider(
            provider_name,
            provider_config,
            config_path.resolve().parent,
        )
        if exit_code != 0:
            return exit_code

    logger.info('all_providers_linked', _display_level=1)
    return 0


def main() -> int:
    """Main entry point for the repolish-link CLI.

    This function keeps a very small surface area and delegates the work to
    `run()`. High-level error handling lives here so callers (and tests) get
    stable exit codes.
    """
    try:
        return run(sys.argv[1:])
    except SystemExit:
        raise
    except FileNotFoundError as e:
        logger.exception('config_not_found', error=str(e))
        return 1
    except RepolishError as e:
        log_exception(logger, e)
        return 1
    except Exception:  # pragma: no cover - high level CLI error handling
        logger.exception('failed_to_run_repolish_link')
        return 1


if __name__ == '__main__':
    sys.exit(main())
