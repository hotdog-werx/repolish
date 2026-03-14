from pathlib import Path

from hotlog import get_logger

from repolish.config import RepolishConfigFile, load_config_file
from repolish.linker.health import ensure_providers_ready

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
    """Run repolish link with the given config."""
    logger.info(
        'loading_config',
        config_file=str(config_path),
        _display_level=1,
    )
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

    result = ensure_providers_ready(
        provider_names,
        config.providers,
        config_path.resolve().parent,
        force=True,
    )

    if result.failed:
        logger.warning(
            'some_providers_not_linked',
            failed=result.failed,
            _display_level=1,
        )
        return 1

    logger.info('all_providers_linked', _display_level=1)
    return 0
