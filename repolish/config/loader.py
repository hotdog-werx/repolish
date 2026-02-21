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


def load_config(yaml_file: Path, *, validate: bool = True) -> RepolishConfig:
    """Load and resolve a repolish configuration from a YAML file.

    Args:
        yaml_file: Path to the YAML configuration file.
        validate: Whether to validate resolved paths. Set to False when linking
                  providers (before .provider-info.json files exist).

    Returns:
        A fully resolved RepolishConfig instance ready for runtime use.
    """
    # Load and validate config file
    config_file = load_config_file(yaml_file)

    # Always validate the raw config structure (pre-resolution)
    validate_config_file(config_file)

    # Resolve all paths and providers
    resolved_config = resolve_config(config_file)

    # Optionally validate resolved paths (post-resolution)
    if validate:
        validate_resolved_config(resolved_config)

    return resolved_config
