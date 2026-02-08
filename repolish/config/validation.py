"""Validation logic for configuration."""

import warnings
from pathlib import Path

from .models import RepolishConfig, RepolishConfigFile


def validate_config_file(config: RepolishConfigFile) -> None:
    """Validate raw configuration file before resolution.

    This performs basic structural validation that doesn't require path resolution.
    Always runs - checks things that Pydantic validators can't catch.

    Args:
        config: Raw configuration loaded from YAML

    Raises:
        ValueError: If configuration structure is invalid
    """
    # Warn if using deprecated directories field
    if config.directories:
        warnings.warn(
            "The 'directories' field is deprecated and will be removed in v1.0. "
            "Use 'providers' with 'directory' configuration instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    # Basic validation: must have either directories or providers_order
    if not config.directories and not config.providers_order:
        msg = 'Configuration must specify either "directories" or "providers_order"'
        raise ValueError(msg)

    # Validate providers_order references only defined providers
    if config.providers_order:
        undefined = [p for p in config.providers_order if p not in config.providers]
        if undefined:
            msg = f'providers_order references undefined providers: {", ".join(undefined)}'
            raise ValueError(msg)


def validate_resolved_config(config: RepolishConfig) -> None:
    """Validate resolved configuration after resolution.

    This checks that resolved paths exist and have required structure.
    Can be skipped when providers aren't linked yet (validate=False).

    Args:
        config: Fully resolved configuration

    Raises:
        ValueError: If resolved paths or structure is invalid
    """
    if not config.directories:
        msg = 'No directories resolved - providers may not be linked yet'
        raise ValueError(msg)

    # Validate directory structure
    _validate_directory_structure(config.directories)

    # Validate provider symlinks
    _validate_provider_symlinks(config)


def _validate_directory_structure(directories: list[Path]) -> None:
    """Validate that directories exist and have required repolish structure.

    Args:
        directories: List of resolved Path objects to validate

    Raises:
        ValueError: If any directories are invalid
    """
    missing_dirs: list[str] = []
    invalid_dirs: list[str] = []
    invalid_template: list[str] = []

    for path in directories:
        path_str = str(path)
        if not path.exists():
            missing_dirs.append(path_str)
        elif not path.is_dir():
            invalid_dirs.append(path_str)
        elif not (path / 'repolish.py').exists() or not (path / 'repolish').exists():
            invalid_template.append(path_str)

    # Report all errors together
    if missing_dirs or invalid_dirs or invalid_template:
        _raise_validation_errors(missing_dirs, invalid_dirs, invalid_template)


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
            # Construct the full source path: target_dir / source
            source_path = provider.target_dir / symlink.source

            if not source_path.exists():
                missing_sources.append(
                    f'{alias}: {symlink.source} (expected at {source_path})',
                )

    if missing_sources:
        error_msg = f'Provider symlink sources not found: {missing_sources}'
        raise ValueError(error_msg)


def _raise_validation_errors(
    missing_dirs: list[str],
    invalid_dirs: list[str],
    invalid_template: list[str],
) -> None:
    """Raise a ValueError with detailed error messages.

    Args:
        missing_dirs: List of directories that don't exist
        invalid_dirs: List of paths that exist but aren't directories
        invalid_template: List of directories missing required structure

    Raises:
        ValueError: Always raises with combined error messages
    """
    error_messages = []
    if missing_dirs:
        error_messages.append(f'Missing directories: {missing_dirs}')
    if invalid_dirs:
        error_messages.append(
            f'Invalid directories (not a directory): {invalid_dirs}',
        )
    if invalid_template:
        error_messages.append(
            f'Directories missing repolish.py or repolish/ folder: {invalid_template}',
        )
    raise ValueError(' ; '.join(error_messages))
