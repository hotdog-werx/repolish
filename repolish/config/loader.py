from pathlib import Path

import yaml

from repolish.config.models import RepolishConfig, RepolishConfigFile
from repolish.config.resolution import resolve_config
from repolish.config.validation import (
    validate_config_file,
    validate_resolved_config,
)


def load_config_file(yaml_file: Path) -> RepolishConfigFile:
    """Load and validate YAML configuration file without resolution.

    Args:
        yaml_file: Path to the YAML configuration file.

    Returns:
        A validated RepolishConfigFile instance (not yet resolved).
    """
    with yaml_file.open(encoding='utf-8') as f:
        data = yaml.safe_load(f)
    config_file = RepolishConfigFile.model_validate(data)
    config_file.config_file = yaml_file
    return config_file


def load_config(
    yaml_file: Path,
    *,
    validate: bool = True,
    provider_filter: list[str] | None = None,
) -> RepolishConfig:
    """Load and resolve a repolish configuration from a YAML file.

    Args:
        yaml_file: Path to the YAML configuration file.
        validate: Whether to validate resolved paths. Set to False when linking
                  providers (before .provider-info.json files exist).
        provider_filter: Optional list of provider aliases to include. If provided,
            only these providers will be loaded from the configuration.

    Returns:
        A fully resolved RepolishConfig instance ready for runtime use.
    """
    # Load and validate config file
    config_file = load_config_file(yaml_file)

    # Always validate the raw config structure (pre-resolution)
    validate_config_file(config_file)

    # Apply provider filter if specified
    if provider_filter is not None:
        # Filter providers dict to only include specified aliases
        filtered_providers = {alias: info for alias, info in config_file.providers.items() if alias in provider_filter}
        # Filter providers_order to maintain order but only include filtered
        if config_file.providers_order:
            filtered_order = [alias for alias in config_file.providers_order if alias in provider_filter]
        else:
            filtered_order = list(filtered_providers.keys())
        config_file = config_file.model_copy(
            update={
                'providers': filtered_providers,
                'providers_order': filtered_order,
            },
        )

    # Resolve all paths and providers
    resolved_config = resolve_config(config_file)

    # Optionally validate resolved paths (post-resolution)
    if validate:
        validate_resolved_config(resolved_config)

    return resolved_config
