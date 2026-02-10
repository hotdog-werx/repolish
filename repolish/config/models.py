from pathlib import Path, PurePosixPath
from typing import Any

from hotlog import get_logger
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from repolish.exceptions import ProviderConfigError

logger = get_logger(__name__)


class ProviderSymlink(BaseModel):
    """Configuration for a provider symlink."""

    source: Path = Field(
        description='Path relative to provider resources (e.g., configs/.editorconfig)',
    )
    target: Path = Field(
        description='Path relative to repo root (e.g., .editorconfig)',
    )

    @field_validator('source', 'target', mode='before')
    @classmethod
    def parse_posix_path(cls, value: str | Path) -> Path:
        """Parse POSIX-style paths from YAML into Path objects.

        YAML files use forward slashes (POSIX), but we need to convert
        them to Path objects that work on the current platform.
        """
        if isinstance(value, Path):
            return value  # pragma: no cover - Already a Path, no need to parse
        # Parse as PurePosixPath first, then convert to platform Path
        # This ensures "configs/.editorconfig" works on Windows
        posix_path = PurePosixPath(value)
        return Path(*posix_path.parts)


class ProviderConfig(BaseModel):
    """Configuration for a single provider."""

    cli: str | None = Field(
        default=None,
        description='CLI command to call for linking (e.g., codeguide-link)',
    )
    directory: str | None = Field(
        default=None,
        description='Direct path to provider directory (alternative to cli)',
    )
    templates_dir: str = Field(
        default='templates',
        description='Subdirectory within provider resources containing templates',
    )
    symlinks: list[ProviderSymlink] = Field(
        default_factory=list,
        description='Additional symlinks to create from provider resources to repo',
    )

    @model_validator(mode='after')
    def validate_cli_or_directory(self) -> 'ProviderConfig':
        """Ensure exactly one of cli or directory is provided."""
        if self.cli is None and self.directory is None:
            msg = 'Either cli or directory must be provided'
            raise ProviderConfigError(msg)
        if self.cli is not None and self.directory is not None:
            msg = 'Cannot specify both cli and directory'
            raise ProviderConfigError(msg)
        return self


class RepolishConfigFile(BaseModel):
    """Configuration for the Repolish tool (internal YAML structure).

    This model represents the raw YAML file format. For runtime use,
    convert this to RepolishConfig using resolve_config().
    """

    directories: list[str] = Field(
        default_factory=list,
        description='DEPRECATED: Use providers instead. List of template directories. Removed in v1.0.',
        deprecated=True,
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


class AllProviders(BaseModel):
    """Model for .all-providers.json file structure.

    This file stores provider alias mappings and can be expanded in the future
    to include additional provider metadata or configuration.

    Aliases map user-friendly names to provider folder names within .repolish/.
    Example: {"aliases": {"base": "codeguide", "py": "python-tools"}}
    """

    aliases: dict[str, str] = Field(
        default_factory=dict,
        description='Mapping of alias names to provider folder names (not full paths)',
    )

    @classmethod
    def from_file(cls, file_path: Path) -> 'AllProviders':
        """Load provider data from JSON file.

        Args:
            file_path: Path to .all-providers.json file

        Returns:
            AllProviders model with empty aliases dict if file doesn't exist or is invalid

        Note:
            Returns a model with empty aliases (not None) because not having this file
            is normal - it just means no provider aliases are configured yet.
        """
        if not file_path.exists():
            return cls()

        try:
            return cls.model_validate_json(file_path.read_text())
        except (ValidationError, ValueError) as e:
            logger.warning(
                'invalid_all_providers_file',
                file=str(file_path),
                error=str(e),
            )
            return cls()


class ProviderInfo(BaseModel):
    """Model for .provider-info.json file structure.

    Contains information about a linked provider.
    """

    target_dir: str = Field(
        description='Directory where provider resources are linked',
    )
    source_dir: str = Field(
        description='Directory where provider resources originate (e.g., in site-packages)',
    )
    templates_dir: str | None = Field(
        default=None,
        description='Subdirectory containing templates (optional)',
    )
    library_name: str | None = Field(
        default=None,
        description='Name of the provider library (optional)',
    )

    @classmethod
    def from_file(cls, file_path: Path) -> 'ProviderInfo | None':
        """Load provider info from JSON file.

        Args:
            file_path: Path to .provider-info.json file

        Returns:
            ProviderInfo instance or None if file doesn't exist or is invalid
        """
        if not file_path.exists():
            logger.debug('provider_info_file_not_found', file=str(file_path))
            return None

        try:
            info = cls.model_validate_json(file_path.read_text())
            logger.debug(
                'loaded_provider_info',
                file=str(file_path),
                data=info.model_dump(),
            )
        except (ValidationError, ValueError) as e:
            logger.warning(
                'invalid_provider_info_file',
                file=str(file_path),
                error=str(e),
            )
            return None
        else:
            return info


class ResolvedProviderInfo(BaseModel):
    """Fully resolved provider information for runtime use.

    This combines data from ProviderConfig (YAML) and ProviderInfo (JSON)
    with all paths resolved and validated.
    """

    alias: str = Field(
        description='Provider alias name used in configuration',
    )
    target_dir: Path = Field(
        description='Fully resolved directory where provider resources are linked',
    )
    templates_dir: str = Field(
        default='templates',
        description='Subdirectory within target_dir containing templates',
    )
    library_name: str | None = Field(
        default=None,
        description='Name of the provider library (optional)',
    )
    symlinks: list[ProviderSymlink] = Field(
        default_factory=list,
        description='Additional symlinks to create from provider resources to repo',
    )


class RepolishConfig(BaseModel):
    """Fully resolved runtime configuration.

    This model represents the configuration after all resolution has been performed:
    - Directories are resolved to absolute Paths
    - Providers are resolved with their full info loaded from JSON
    - All aliases are resolved
    - All relative paths are made absolute based on config_file location
    """

    config_dir: Path = Field(
        description='Directory containing the repolish.yaml file',
    )
    directories: list[Path] = Field(
        default_factory=list,
        description='Fully resolved template directory paths',
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description='Context variables for template rendering',
    )
    context_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description='Overrides for context variables',
    )
    anchors: dict[str, str] = Field(
        default_factory=dict,
        description='Anchor content for block replacements',
    )
    post_process: list[str] = Field(
        default_factory=list,
        description='List of shell commands to run after generating files',
    )
    delete_files: list[str] = Field(
        default_factory=list,
        description='List of POSIX-style paths to delete after generation',
    )
    providers: dict[str, ResolvedProviderInfo] = Field(
        default_factory=dict,
        description='Fully resolved provider information',
    )
    providers_order: list[str] = Field(
        default_factory=list,
        description='Order in which to process providers',
    )
