from pathlib import Path
from typing import cast

from hotlog import get_logger

from repolish.config.models import (
    ProviderConfig,
    RepolishConfig,
    RepolishConfigFile,
    ResolvedProviderInfo,
)
from repolish.config.models.metadata import ProviderFileInfo
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
        config_dir=config_dir,
        post_process=config.post_process,
        delete_files=config.delete_files,
        providers=resolved_providers,
        providers_order=config.providers_order,
        template_overrides=config.template_overrides,
        paused_files=config.paused_files,
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


def _try_auto_link(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> ProviderFileInfo | None:
    """Attempt to auto-link via the provider CLI and reload the info file."""
    from repolish.linker import (  # noqa: PLC0415 - deferred to avoid circular import
        process_provider,
    )

    logger.warning(
        'provider_directory_missing',
        alias=alias,
        suggestion='provider directory not found; attempting to link via cli',
        cli=provider_config.cli,
    )
    exit_code = process_provider(alias, provider_config, config_dir)
    if exit_code == 0:
        return load_provider_info(alias, config_dir)
    logger.warning(
        'provider_auto_link_failed',
        alias=alias,
        cli=provider_config.cli,
        exit_code=exit_code,
    )
    return None


def _resolved_from_info(
    alias: str,
    provider_config: ProviderConfig,
    provider_info: ProviderFileInfo,
    config_dir: Path,
) -> ResolvedProviderInfo:
    """Build a ResolvedProviderInfo from a loaded ProviderFileInfo JSON file."""
    resources_dir = _resolve_path(provider_info.resources_dir, config_dir)
    provider_root = (
        _resolve_path(provider_info.provider_root, config_dir) if provider_info.provider_root else resources_dir
    )
    symlinks = provider_config.symlinks or []
    return ResolvedProviderInfo(
        alias=alias,
        provider_root=provider_root,
        resources_dir=resources_dir,
        symlinks=symlinks,
        context=provider_config.context,
        context_overrides=provider_config.context_overrides or None,
    )


def _resolved_from_static(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> ResolvedProviderInfo:
    """Build a ResolvedProviderInfo from explicit provider_root (and optional resources_dir) fields."""
    if provider_config.provider_root is None:
        msg = 'provider_root must be set at this point'
        raise ValueError(msg)
    provider_root = _resolve_path(provider_config.provider_root, config_dir)
    resources_dir = (
        _resolve_path(provider_config.resources_dir, config_dir) if provider_config.resources_dir else provider_root
    )
    symlinks = provider_config.symlinks if provider_config.symlinks is not None else []
    return ResolvedProviderInfo(
        alias=alias,
        provider_root=provider_root,
        resources_dir=resources_dir,
        symlinks=symlinks,
        context=provider_config.context,
        context_overrides=provider_config.context_overrides or None,
    )


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
    provider_info = load_provider_info(alias, config_dir)

    if provider_info is None and provider_config.cli:
        provider_info = _try_auto_link(alias, provider_config, config_dir)

    if provider_info:
        if provider_config.provider_root:
            logger.warning(
                'provider_root_ignored',
                alias=alias,
                reason='provider-info file found; provider_root is ignored',
            )
        return _resolved_from_info(
            alias,
            provider_config,
            provider_info,
            config_dir,
        )

    if provider_config.provider_root:
        return _resolved_from_static(alias, provider_config, config_dir)

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
