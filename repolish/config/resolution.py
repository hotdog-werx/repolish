from pathlib import Path
from typing import cast

from hotlog import get_logger

from .models import (
    ProviderConfig,
    RepolishConfig,
    RepolishConfigFile,
    ResolvedProviderInfo,
)
from .providers import load_provider_info

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

    # Resolve directories (either explicit or from providers)
    directories = _resolve_directories(config, config_dir)

    # Resolve all providers
    resolved_providers = _resolve_providers(config, config_dir)

    return RepolishConfig(
        no_cookiecutter=config.no_cookiecutter,
        config_dir=config_dir,
        directories=directories,
        context=config.context,
        context_overrides=config.context_overrides,
        anchors=config.anchors,
        post_process=config.post_process,
        delete_files=config.delete_files,
        providers=resolved_providers,
        providers_order=config.providers_order,
    )


def _resolve_directories(
    config: RepolishConfigFile,
    config_dir: Path,
) -> list[Path]:
    """Resolve directory configuration to absolute Path objects.

    If directories are explicitly configured, resolve them.
    If providers are configured, build directories from providers
    (using providers_order if specified, else providers dict key order).

    Args:
        config: Raw configuration
        config_dir: Directory containing the config file

    Returns:
        List of resolved directory paths
    """
    # If directories is explicitly set, resolve them
    # Note: directories field is deprecated, but if it's still used, we resolve it directly
    if config.directories:
        return _resolve_directory_list(config.directories, config_dir)

    # Otherwise, build from providers (using providers_order if specified, else dict key order)
    if config.providers:
        return _build_directories_from_providers(config, config_dir)

    # No directories configured
    return []  # pragma: no cover - This should be caught by validation before resolution


def _resolve_directory_list(
    directories: list[str],
    config_dir: Path,
) -> list[Path]:
    """Resolve a list of directory strings to absolute Path objects.

    Args:
        directories: List of directory paths from config
        config_dir: Directory containing the config file

    Returns:
        List of resolved absolute Path objects
    """
    return [_resolve_path(entry, config_dir) for entry in directories]


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
            target_dir=target_dir,
            templates_dir=provider_info.templates_dir or provider_config.templates_dir,
            library_name=provider_info.library_name,
            symlinks=symlinks,
        )
    if provider_config.directory:
        # Use direct directory from config
        target_dir = _resolve_path(provider_config.directory, config_dir)
        # For directory providers, use user symlinks or empty list as default
        symlinks = provider_config.symlinks if provider_config.symlinks is not None else []
        return ResolvedProviderInfo(
            alias=alias,
            target_dir=target_dir,
            templates_dir=provider_config.templates_dir,
            library_name=None,
            symlinks=symlinks,
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


def _build_directories_from_providers(
    config: RepolishConfigFile,
    config_dir: Path,
) -> list[Path]:
    """Build directories list from providers.

    Uses providers_order if specified, otherwise uses providers dict key order.

    Args:
        config: Raw configuration
        config_dir: Directory containing the config file

    Returns:
        List of resolved directory paths from providers
    """
    resolved = []
    # Use providers_order if specified, else use providers dict key order (preserves YAML order)
    provider_names = config.providers_order if config.providers_order else list(config.providers.keys())

    for provider_name in provider_names:
        templates_path = _get_provider_templates_dir(
            config,
            provider_name,
            config_dir,
        )
        if templates_path:
            resolved.append(templates_path)

    return resolved


def _get_provider_templates_dir(
    config: RepolishConfigFile,
    provider_name: str,
    config_dir: Path,
) -> Path | None:
    """Get the templates directory path from a provider.

    Args:
        config: Raw configuration
        provider_name: Name of the provider
        config_dir: Directory containing the config file

    Returns:
        Resolved template directory path, or None if provider cannot be resolved
    """
    provider_config = config.providers.get(provider_name)
    if not provider_config:  # pragma: no cover - validation ensures providers_order only references defined providers
        logger.warning('provider_not_found_in_config', provider=provider_name)
        return None

    # If provider has a direct directory, use it
    if provider_config.directory:
        directory = _resolve_path(provider_config.directory, config_dir)
        templates_path = directory / provider_config.templates_dir
        logger.debug(
            'auto_added_directory_from_provider',
            provider=provider_name,
            directory=str(templates_path),
            source='direct_directory',
        )
        return templates_path

    # Otherwise, try to load from linked provider info
    provider_info = load_provider_info(provider_name, config_dir)
    if not provider_info:
        logger.warning('could_not_load_provider_info', provider=provider_name)
        return None

    # Get target_dir and templates_dir from provider info
    target_dir = _resolve_path(provider_info.target_dir, config_dir)
    templates_subdir = provider_info.templates_dir or provider_config.templates_dir
    templates_path = target_dir / templates_subdir

    logger.debug(
        'auto_added_directory_from_provider',
        provider=provider_name,
        directory=str(templates_path),
        source='linked_provider',
    )
    return templates_path
