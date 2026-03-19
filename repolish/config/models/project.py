from pathlib import Path

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from repolish.config.models.provider import ProviderConfig, ResolvedProviderInfo
from repolish.exceptions import ConfigValidationError


class WorkspaceConfig(BaseModel):
    """Optional workspace section in ``repolish.yaml``.

    When present, enables workspace mode.  When ``members`` is set it overrides
    auto-detection from ``[tool.uv.workspace]`` in ``pyproject.toml``.
    """

    members: list[str] | None = None
    """Explicit repo-relative member paths. Overrides uv workspace detection."""


class RepolishConfigFile(BaseModel):
    """Configuration for the Repolish tool (internal YAML structure).

    This model represents the raw YAML file format. For runtime use,
    convert this to RepolishConfig using resolve_config().
    """

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
        description='Optional: Order in which to process providers. Defaults to providers dict key order from YAML.',
    )
    template_overrides: dict[str, str] = Field(
        default_factory=dict,
        description=(
            'Optional mapping of glob-style file patterns to provider aliases. '
            'Overrides which provider supplies a given file regardless of the '
            'usual provider order. Keys are POSIX-style file paths, values must '
            'reference a defined provider alias.'
        ),
    )
    paused_files: list[str] = Field(
        default_factory=list,
        description=(
            'Temporary list of POSIX-style file paths that repolish should '
            'ignore. Use this to opt out of provider management for specific '
            'files while a provider is being fixed or updated. Remove entries '
            'once the underlying provider issue is resolved.'
        ),
    )
    providers: dict[str, ProviderConfig] = Field(
        default_factory=dict,
        description='Provider configurations for resource linking and orchestration',
    )
    workspace: WorkspaceConfig | None = Field(
        default=None,
        description=(
            'Optional workspace configuration. When present, enables workspace mode. '
            'members overrides auto-detection from [tool.uv.workspace].'
        ),
    )
    # Path to the YAML configuration file. Set when loading from disk; excluded
    # from model serialization so it doesn't appear in dumped config data.
    config_file: Path | None = Field(
        default=None,
        description='Path to the YAML configuration file (set by loader)',
        exclude=True,
    )

    @field_validator('providers', mode='before')
    @classmethod
    def normalize_provider_configs(
        cls,
        value: dict[str, object],
    ) -> dict[str, object]:
        """Normalize provider configurations from shorthand string to full ProviderConfig.

        Supports shorthand syntax where the value is just the CLI command:
            providers:
              base: codeguide-link

        Which is equivalent to:
            providers:
              base:
                cli: codeguide-link

        Args:
            value: Raw provider configurations from YAML (always a dict due to field type)

        Returns:
            Normalized provider configurations (dict or ProviderConfig objects)
        """
        normalized: dict[str, object] = {}
        for name, config in value.items():
            if isinstance(config, str):
                # Shorthand: treat string as CLI command
                normalized[name] = {'cli': config}
            else:
                normalized[name] = config

        return normalized

    @model_validator(mode='after')
    def validate_template_overrides(self) -> 'RepolishConfigFile':
        """Ensure every alias referenced in template_overrides is defined.

        This validator runs after the entire model is built so we can access
        both the overrides mapping and the providers dict.
        """
        if self.template_overrides:
            unknown = set(self.template_overrides.values()) - set(
                self.providers.keys(),
            )
            if unknown:
                msg = f'template_overrides references undefined providers: {sorted(unknown)}'
                raise ConfigValidationError(msg)
        return self


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
    template_overrides: dict[str, str] = Field(
        default_factory=dict,
        description=(
            'Mapping of glob patterns to provider aliases after resolution. '
            'Inherited directly from `RepolishConfigFile.template_overrides`.'
        ),
    )
    paused_files: list[str] = Field(
        default_factory=list,
        description=(
            'Temporary list of files repolish will not touch. '
            'Inherited directly from `RepolishConfigFile.paused_files`.'
        ),
    )
