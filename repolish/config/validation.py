from repolish.config.models import RepolishConfig, RepolishConfigFile
from repolish.exceptions import (
    ConfigValidationError,
    DirectoryValidationError,
    ProviderOrderError,
)


def validate_config_file(config: RepolishConfigFile) -> None:
    """Validate raw configuration file before resolution.

    This performs basic structural validation that doesn't require path resolution.
    Always runs - checks things that Pydantic validators can't catch.

    Args:
        config: Raw configuration loaded from YAML

    Raises:
        ValueError: If configuration structure is invalid
    """
    # Basic validation: must have at least one provider defined
    # (directories were removed in v1.0)
    if not config.providers:
        msg = 'Configuration must specify at least one provider'
        raise ConfigValidationError(msg)

    # Validate providers_order references only defined providers
    if config.providers_order:
        undefined = [p for p in config.providers_order if p not in config.providers]
        if undefined:
            msg = f'providers_order references undefined providers: {", ".join(undefined)}'
            raise ProviderOrderError(msg)


def validate_resolved_config(config: RepolishConfig) -> None:
    """Validate resolved configuration after resolution.

    This checks that resolved paths exist and have required structure.
    Can be skipped when providers aren't linked yet (validate=False).

    Args:
        config: Fully resolved configuration

    Raises:
        ValueError: If resolved paths or structure is invalid
    """
    # directories removed; we still require at least one provider for structure
    if not config.providers:
        msg = 'No providers resolved - configuration may be empty'
        raise DirectoryValidationError(msg)

    # Validate provider symlinks
    _validate_provider_symlinks(config)


def _validate_provider_symlinks(config: RepolishConfig) -> None:
    """Validate that all provider symlink sources exist.

    Args:
        config: Fully resolved configuration

    Raises:
        ValueError: If any symlink source files are missing
    """
    missing_sources: list[str] = []

    for alias, provider in config.providers.items():
        for symlink in provider.symlinks:
            # Symlink sources are relative to the resources root, not the templates subdir
            source_path = provider.resources_dir / symlink.source

            if not source_path.exists():
                missing_sources.append(
                    f'{alias}: {symlink.source} (expected at {source_path})',
                )

    if missing_sources:
        error_msg = f'Provider symlink sources not found: {missing_sources}'
        raise DirectoryValidationError(error_msg)
