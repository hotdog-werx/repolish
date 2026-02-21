"""High-level provider processing orchestration."""

import subprocess
from pathlib import Path

from hotlog import get_logger

from repolish.config.models import ProviderConfig, ProviderInfo
from repolish.linker.providers import run_provider_link, save_provider_info
from repolish.linker.symlinks import create_additional_link

logger = get_logger(__name__)


def create_provider_symlinks(
    provider_name: str,
    provider_info: ProviderInfo,
    symlinks: list,  # list of ProviderSymlink
) -> None:
    """Create additional symlinks for a provider.

    Args:
        provider_name: Name of the provider
        provider_info: Provider information from the CLI --info
        symlinks: List of symlink configurations
    """
    if not symlinks:
        return

    logger.info(
        'creating_additional_symlinks',
        provider=provider_name,
        count=len(symlinks),
        _display_level=1,
    )

    for symlink in symlinks:
        logger.debug(
            'creating_symlink',
            source=str(symlink.source),
            target=str(symlink.target),
        )

        create_additional_link(
            provider_info=provider_info,
            provider_name=provider_name,
            source=str(symlink.source),
            target=str(symlink.target),
            force=True,
        )

    logger.info(
        'symlinks_created',
        provider=provider_name,
        count=len(symlinks),
        _display_level=1,
    )


def process_provider(
    provider_name: str,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> int:
    """Process a single provider: link resources and create symlinks.

    Args:
        provider_name: Name of the provider
        provider_config: Provider configuration
        config_dir: Directory containing the repolish.yaml file

    Returns:
        0 on success, 1 on failure
    """
    # Skip providers that use direct directory (no CLI to run)
    if not provider_config.cli:
        logger.info(
            'skipping_provider_with_directory',
            provider=provider_name,
            _display_level=1,
        )
        return 0

    # Run the provider's link CLI
    try:
        provider_info = run_provider_link(
            provider_name,
            provider_config.cli,
        )
    except subprocess.CalledProcessError as e:
        logger.exception(
            'provider_link_failed',
            provider=provider_name,
            error=str(e),
        )
        return 1
    except FileNotFoundError:
        logger.exception(
            'provider_cli_not_found',
            provider=provider_name,
            command=provider_config.cli,
        )
        return 1

    # Save provider info
    save_provider_info(provider_name, provider_info, config_dir)

    # Create additional symlinks based on configuration
    # - None (default): use provider's default symlinks
    # - Empty list []: skip symlinks entirely
    # - Non-empty list: use specified symlinks
    if provider_config.symlinks is None:
        # Use provider defaults
        symlinks_to_create = provider_info.symlinks
    elif provider_config.symlinks:
        # Use configured symlinks
        symlinks_to_create = provider_config.symlinks
    else:
        # Empty list - skip symlinks
        symlinks_to_create = []

    if symlinks_to_create:
        create_provider_symlinks(
            provider_name,
            provider_info,
            symlinks_to_create,
        )

    return 0
