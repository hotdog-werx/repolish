from pathlib import Path

from hotlog import get_logger

from repolish.config import load_config_file
from repolish.config.models import RepolishConfigFile
from repolish.linker import process_provider

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


def command(config_path: Path) -> int:
    """Run repolish-link with the given config."""
    # Logging is already configured in the link function

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
