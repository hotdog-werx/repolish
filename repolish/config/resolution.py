from pathlib import Path
from typing import cast

from hotlog import get_logger

from repolish.config.models import (
    ProviderConfig,
    RepolishConfig,
    RepolishConfigFile,
    ResolvedProviderInfo,
)
from repolish.config.providers import load_provider_info

logger = get_logger(__name__)


def resolve_config(config: RepolishConfigFile) -> RepolishConfig:
    """Resolve a raw configuration into fully resolved runtime configuration.

    This performs all necessary resolution:
    - Resolves directories to absolute Paths
    - Loads and resolves all provider information
    - Resolves all relative paths based on config file location

    Args:
        config: Raw configuration loaded from YAML (config_file must be set by caller)

    Returns:
        Fully resolved configuration ready for runtime use
    """
    # Safe to cast: loader.load_config() always sets config_file before calling this
    config_file = cast('Path', config.config_file)
    config_dir = config_file.resolve().parent

    # directories are determined solely from providers; resolved later as needed

    # Resolve all providers
    resolved_providers = _resolve_providers(config, config_dir)

    return RepolishConfig(
        provider_scoped_template_context=config.provider_scoped_template_context,
        config_dir=config_dir,
        post_process=config.post_process,
        delete_files=config.delete_files,
        providers=resolved_providers,
        providers_order=config.providers_order,
        template_overrides=config.template_overrides,
    )


def _resolve_providers(
    config: RepolishConfigFile,
    config_dir: Path,
) -> dict[str, ResolvedProviderInfo]:
    """Resolve all provider configurations.

    Args:
        config: Raw configuration
        config_dir: Directory containing the config file

    Returns:
        Dictionary of resolved provider information
    """
    resolved_providers: dict[str, ResolvedProviderInfo] = {}

    for alias, provider_config in config.providers.items():
        resolved_info = _resolve_single_provider(
            alias,
            provider_config,
            config_dir,
        )
        if resolved_info:
            resolved_providers[alias] = resolved_info

    return resolved_providers


def _resolve_single_provider(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> ResolvedProviderInfo | None:
    """Resolve a single provider configuration.

    Args:
        alias: Provider alias name
        provider_config: Provider configuration from YAML
        config_dir: Directory containing the config file

    Returns:
        Resolved provider info, or None if cannot be resolved
    """
    # Try to load provider info from JSON file (if linked)
    provider_info = load_provider_info(alias, config_dir)

    if provider_info:
        # Use info from linked provider
        target_dir = _resolve_path(provider_info.target_dir, config_dir)
        # Use user-specified symlinks if provided, otherwise use provider defaults
        symlinks = provider_config.symlinks if provider_config.symlinks is not None else provider_info.symlinks
        return ResolvedProviderInfo(
            alias=alias,
            # `target_dir` should already point at templates root
            target_dir=target_dir,
            library_name=provider_info.library_name,
            symlinks=symlinks,
            context=provider_config.context,
            context_overrides=provider_config.context_overrides or None,
        )
    if provider_config.directory:
        # Use direct directory from config
        target_dir = _resolve_path(provider_config.directory, config_dir)
        # For directory providers, use user symlinks or empty list as default
        symlinks = provider_config.symlinks if provider_config.symlinks is not None else []
        return ResolvedProviderInfo(
            alias=alias,
            target_dir=target_dir,
            library_name=None,
            symlinks=symlinks,
            context=provider_config.context,
            context_overrides=provider_config.context_overrides or None,
        )
    # Neither info file nor directory config
    logger.warning(
        'provider_not_resolved',
        alias=alias,
        reason='No provider info file or directory configuration found',
    )
    return None


def _resolve_path(path: str | Path, base_dir: Path) -> Path:
    """Resolve a path relative to a base directory.

    Args:
        path: Path string or Path object to resolve
        base_dir: Base directory for relative paths

    Returns:
        Resolved absolute Path
    """
    p = Path(path)
    return p.resolve() if p.is_absolute() else (base_dir / p).resolve()
