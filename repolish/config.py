import json
from pathlib import Path
from typing import Any

import yaml
from hotlog import get_logger
from pydantic import BaseModel, Field

logger = get_logger(__name__)


class ProviderSymlink(BaseModel):
    """Configuration for a provider symlink."""

    source: str = Field(
        description='Path relative to provider resources (e.g., configs/.editorconfig)',
    )
    target: str = Field(
        description='Path relative to repo root (e.g., .editorconfig)',
    )


class ProviderConfig(BaseModel):
    """Configuration for a single provider."""

    link: str = Field(
        description='CLI command to call for linking (e.g., codeguide-link)',
    )
    templates_dir: str = Field(
        default='templates',
        description='Subdirectory within provider resources containing templates',
    )
    symlinks: list[ProviderSymlink] = Field(
        default_factory=list,
        description='Additional symlinks to create from provider resources to repo',
    )


class RepolishConfig(BaseModel):
    """Configuration for the Repolish tool."""

    directories: list[str] = Field(
        default_factory=list,
        description='List of paths to template directories',
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description='Context variables for template rendering',
    )
    context_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description='Overrides for context variables using dot-notation paths or nested dict structures',
    )
    anchors: dict[str, str] = Field(
        default_factory=dict,
        description='Anchor content for block replacements',
    )
    post_process: list[str] = Field(
        default_factory=list,
        description='List of shell commands to run after generating files (formatters)',
    )
    delete_files: list[str] = Field(
        default_factory=list,
        description=(
            'List of POSIX-style paths to delete after generation. Use a leading'
            " '!' to negate (keep) a previously-added path."
        ),
    )
    providers_order: list[str] = Field(
        default_factory=list,
        description='Order in which to process providers for template processing',
    )
    providers: dict[str, ProviderConfig] = Field(
        default_factory=dict,
        description='Provider configurations for resource linking and orchestration',
    )
    # Path to the YAML configuration file. Set when loading from disk; excluded
    # from model serialization so it doesn't appear in dumped config data.
    config_file: Path | None = Field(
        default=None,
        description='Path to the YAML configuration file (set by loader)',
        exclude=True,
    )

    def _handle_directory_errors(
        self,
        missing_dirs: list[str],
        invalid_dirs: list[str],
        invalid_template: list[str],
    ) -> None:
        """Handle errors related to directory validation."""
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
        if error_messages:
            raise ValueError(' ; '.join(error_messages))

    def _validate_directory_list(
        self,
        directories: list[str],
        resolved_dirs: list[Path],
    ) -> None:
        """Validate a list of directories and their resolved paths."""
        missing_dirs: list[str] = []
        invalid_dirs: list[str] = []
        invalid_template: list[str] = []

        for directory in resolved_dirs:
            # Keep the user-facing identifier as the original string for
            # clearer error messages; find the matching input string by index.
            idx = resolved_dirs.index(directory)
            original = directories[idx]
            path = directory
            if not path.exists():
                missing_dirs.append(original)
            elif not path.is_dir():
                invalid_dirs.append(original)
            elif not (path / 'repolish.py').exists() or not (path / 'repolish').exists():
                invalid_template.append(original)

        if missing_dirs or invalid_dirs or invalid_template:
            self._handle_directory_errors(
                missing_dirs,
                invalid_dirs,
                invalid_template,
            )

    def validate_directories(self) -> None:
        """Validate that all directories exist and have required structure.
        
        Note: directories should already be populated by load_config() if using providers.
        """
        if not self.directories:
            # If using providers_order, directories might be empty if providers not yet linked
            if self.providers_order:
                return  # Skip validation - providers not linked yet
            msg = 'No directories configured'
            raise ValueError(msg)

        # Resolve and validate
        resolved_dirs = self._resolve_directories(self.directories)
        self._validate_directory_list(self.directories, resolved_dirs)

    def _resolve_directories(self, directories: list[str]) -> list[Path]:
        """Resolve a list of directory strings to Path objects."""
        resolved: list[Path] = []
        base_dir = Path(self.config_file).resolve().parent if self.config_file else None

        for entry in directories:
            # Accept POSIX-style entries (forward slashes) but let the
            # platform-native Path handle parsing so absolute Windows-style
            # entries like 'C:/path' are recognized correctly. If the entry
            # is relative, resolve it against the directory containing the
            # config file (when available).
            p = Path(entry)
            if base_dir and not p.is_absolute():
                p = base_dir / p
            resolved.append(p.resolve())

        return resolved

    def _handle_directory_from_provider(
        self,
        provider_name: str,
        config_dir: Path,
    ) -> Path | None:
        """Build directory path from a single provider.

        Returns None if the provider info cannot be loaded.
        """
        provider_info = _load_provider_info(provider_name, config_dir)
        if not provider_info or 'target_dir' not in provider_info:
            logger.warning(
                'could_not_load_provider_info',
                provider=provider_name,
            )
            return None

        # Get target_dir from provider info (where resources are linked)
        target_dir = Path(provider_info['target_dir'])
        if not target_dir.is_absolute():
            target_dir = config_dir / target_dir

        # Get templates_dir: prioritize JSON, then YAML config, then default
        if 'templates_dir' in provider_info:
            templates_subdir = provider_info['templates_dir']
        else:
            provider_config = self.providers.get(provider_name)
            templates_subdir = provider_config.templates_dir if provider_config else 'templates'

        # Combine to get full templates path
        templates_path = target_dir / templates_subdir
        logger.debug(
            'auto_added_directory_from_provider',
            provider=provider_name,
            directory=str(templates_path),
        )
        return templates_path.resolve()

    def _build_directories_from_providers(self) -> list[Path]:
        """Build directories list from providers_order."""
        if not self.providers_order or not self.config_file:
            return []

        config_dir = Path(self.config_file).resolve().parent
        resolved = []

        for provider_name in self.providers_order:
            templates_path = self._handle_directory_from_provider(
                provider_name,
                config_dir,
            )
            if templates_path:
                resolved.append(templates_path)

        return resolved

    def get_directories(self) -> list[Path]:
        """Return the configured directories as resolved Path objects.

        The YAML configuration file is expected to use POSIX-style paths (with
        forward slashes). This method interprets each configured string as a
        POSIX path and resolves it relative to the directory containing the
        configuration file (if `config_file` is set). If `config_file` is not
        set, paths are returned as-is (interpreted by the current platform).

        If directories is empty but providers_order is set, auto-build directories
        from linked provider info.
        """
        # If directories is explicitly set, use them
        if self.directories:
            return self._resolve_directories(self.directories)

        # Auto-build from providers_order
        return self._build_directories_from_providers()


def _resolve_provider_alias(
    provider_name: str,
    config_dir: Path,
) -> str | None:
    """Resolve a provider alias to its actual directory path.

    Args:
        provider_name: Provider name (may be an alias)
        config_dir: Directory containing the repolish.yaml file

    Returns:
        Relative path to provider directory, or None if not an alias
    """
    aliases_file = config_dir / '.repolish' / '.provider-aliases.json'
    if not aliases_file.exists():
        return None

    try:
        with aliases_file.open('r') as f:
            aliases = json.load(f)
        return aliases.get(provider_name)
    except (json.JSONDecodeError, OSError):  # nopragma: no cover - error path not easily exercised in tests
        return None


def _load_provider_info(
    provider_name: str,
    config_dir: Path,
) -> dict[str, Any] | None:
    """Load provider info from .repolish/<provider>/.provider-info.json.

    Supports provider aliases by checking .provider-aliases.json first.

    Args:
        provider_name: Name of the provider (may be an alias)
        config_dir: Directory containing the repolish.yaml file

    Returns:
        Provider info dict or None if not found
    """
    # Check if provider_name is an alias
    actual_dir = _resolve_provider_alias(provider_name, config_dir)
    provider_dir = config_dir / actual_dir if actual_dir else config_dir / '.repolish' / provider_name

    info_file = provider_dir / '.provider-info.json'

    if not info_file.exists():
        logger.debug('provider_info_file_not_found', file=str(info_file))
        return None

    try:
        with info_file.open('r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(
            'invalid_json_in_provider_info',
            file=str(info_file),
            error=str(e),
        )
        return None
    except OSError as e:
        logger.warning(
            'error_reading_provider_info',
            file=str(info_file),
            error=str(e),
        )
        return None
    else:
        logger.debug(
            'loaded_provider_info',
            provider=provider_name,
            data=data,
        )
        return data


def load_config(yaml_file: Path, *, validate: bool = True) -> RepolishConfig:
    """Find the repolish configuration file in the specified directory.

    Args:
        yaml_file: Path to the YAML configuration file.
        validate: Whether to validate directories. Set to False when linking
                  providers (before .provider-info.json files exist).

    Returns:
        An instance of RepolishConfig with validated data.
    """
    with yaml_file.open(encoding='utf-8') as f:
        data = yaml.safe_load(f)
    config = RepolishConfig.model_validate(data)
    # store the location of the config file on the model so relative paths can
    # be resolved later
    config.config_file = yaml_file
    
    # If directories is empty but providers_order is set, auto-populate from providers
    # Skip this during linking (validate=False) since provider info doesn't exist yet
    if validate and not config.directories and config.providers_order:
        resolved_dirs = config.get_directories()
        # Convert back to strings for the config model
        config.directories = [str(d) for d in resolved_dirs]
    
    if validate:
        config.validate_directories()
    return config
