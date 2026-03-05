from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from repolish.config.models.provider import ProviderConfig
from repolish.exceptions import ConfigValidationError


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
    # Opt-in: allow users to disable cookiecutter rendering and instead use
    # Jinja2 directly on the staged templates. Default is False (use
    # cookiecutter) to preserve existing behavior.
    no_cookiecutter: bool = Field(
        default=False,
        description=(
            'When true, skip cookiecutter and render templates with Jinja2 using the merged provider context (opt-in).'
        ),
    )
    provider_scoped_template_context: bool = Field(
        default=True,
        description=(
            'Legacy flag preserved for backwards compatibility. The default is '
            '`true` and new class-based providers use their own context '
            'automatically when migrated.  The only remaining use-case for '
            'setting this to `false` is inside the old module-adapter '
            'implementation, which globally forces merged-context rendering. '
            'Most users never need to touch this setting.'
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

    @field_validator('providers', mode='before')
    @classmethod
    def normalize_provider_configs(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
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
        normalized: dict[str, Any] = {}
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
    # Opt-in: when true, skip calling cookiecutter and render templates with
    # Jinja2 directly using `providers.context`. Default is False to preserve
    # the existing cookiecutter-based behavior.
    no_cookiecutter: bool = Field(
        default=False,
        description=(
            'If true, render templates with Jinja2 directly and skip cookiecutter (opt-in experimental feature).'
        ),
    )
    provider_scoped_template_context: bool = Field(
        default=False,
        description=(
            'When true, render per-mapping `TemplateMapping` entries '
            "using only the declaring provider's context. Opt-in and may "
            'break templates that rely on merged context.'
        ),
    )
    providers: dict[str, Any] = Field(
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
