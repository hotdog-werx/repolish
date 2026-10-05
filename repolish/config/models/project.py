import shutil
from enum import Enum
from importlib.util import find_spec
from pathlib import Path

from hotlog import get_logger
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from repolish.config.models.provider import ProviderConfig, ResolvedProviderInfo
from repolish.exceptions import ConfigValidationError

logger = get_logger(__name__)


def _shorthand_is_provider_package(name: str) -> bool:
    """Return True when *name* resolves to an importable package.

    Mirrors the module-link probe's requirement
    (:func:`repolish.linker.module_link._package_root`): a provider module
    must resolve to a package directory, not a plain module.
    """
    try:
        spec = find_spec(name)
    except (ModuleNotFoundError, ValueError):
        return False
    return spec is not None and bool(spec.submodule_search_locations)


def _expand_provider_shorthand(alias: str, value: str) -> dict[str, str]:
    """Expand a bare-string provider entry, module first.

    The shorthand prefers ``module:``: when the string resolves to an
    installed package it becomes a module provider. Otherwise it keeps the
    legacy meaning (``cli:``), warning when the command exists, since v2 will
    require the shorthand to name a valid module.
    """
    if _shorthand_is_provider_package(value):
        return {'module': value}
    if shutil.which(value) is not None:
        logger.warning(
            'provider_shorthand_cli_fallback',
            alias=alias,
            command=value,
            hint='v2 will require the provider shorthand to be a valid module name; write module: or cli: explicitly',
        )
    return {'cli': value}


class WorkspaceConfig(BaseModel):
    """Optional workspace section in ``repolish.yaml``.

    When present, enables workspace mode.  When ``members`` is set it overrides
    auto-detection from ``[tool.uv.workspace]`` in ``pyproject.toml``.
    """

    members: list[str] | None = None
    """Explicit repo-relative member paths. Overrides uv workspace detection."""


class FastLaneResolution(str, Enum):
    """Which side wins when a regular hook and a fast lane declare one dest."""

    FAST_LANE = 'fast_lane'
    REGULAR = 'regular'


class FastLaneConfig(BaseModel):
    """Per-lane settings from the ``fast_lanes.config`` section.

    The keys of the surrounding mapping are lane names. ``post_process`` is
    the first field; the model is deliberately extensible so future
    per-lane settings land here.
    """

    post_process: list[str] = Field(
        default_factory=list,
        description=(
            'Post-process commands for this lane, run against the render '
            'tree in apply and check mode alike. Replaces the project-wide '
            'post_process in a named lane run (a lane with no entry runs '
            'no post_process at all).'
        ),
    )


class FastLanesSection(BaseModel):
    """The top-level ``fast_lanes`` section in ``repolish.yaml``."""

    resolutions: dict[str, FastLaneResolution] = Field(
        default_factory=dict,
        description=(
            'Resolves a dest declared by both a regular provider hook and a '
            "fast lane. 'fast_lane' keeps the lane's contribution everywhere; "
            "'regular' keeps the regular hook's entry (lane runs then skip "
            'the dest). Without an entry here, such a collision is an error.'
        ),
    )
    config: dict[str, FastLaneConfig] = Field(
        default_factory=dict,
        description='Per-lane settings, keyed by lane name.',
    )


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
    template_overrides: dict[str, str | None] = Field(
        default_factory=dict,
        description=(
            'Optional mapping of glob-style file patterns to provider aliases. '
            'Overrides which provider supplies a given file regardless of the '
            'usual provider order. Keys are POSIX-style file paths, values must '
            'reference a defined provider alias, or null/~ to suppress the '
            'file entirely (it will not be staged or rendered).'
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
    fast_lanes: FastLanesSection = Field(
        default_factory=FastLanesSection,
        description='Fast lane section: dest resolutions and per-lane config.',
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

        Supports shorthand syntax where the value is a single string, resolved
        module first (see :func:`_expand_provider_shorthand`):
            providers:
              base: devkit.workspace

        Which is equivalent to:
            providers:
              base:
                module: devkit.workspace

        Args:
            value: Raw provider configurations from YAML (always a dict due to field type)

        Returns:
            Normalized provider configurations (dict or ProviderConfig objects)
        """
        normalized: dict[str, object] = {}
        for name, config in value.items():
            if isinstance(config, str):
                normalized[name] = _expand_provider_shorthand(name, config)
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
            unknown = {alias for alias in self.template_overrides.values() if alias is not None} - set(
                self.providers.keys()
            )
            if unknown:
                msg = f'template_overrides references undefined providers: {sorted(unknown)}'
                raise ConfigValidationError(msg)
        return self


class RepolishConfig(BaseModel):
    """Fully resolved runtime configuration.

    This model represents the configuration after all resolution has been performed:
    - Directories are resolved to absolute Paths
    - SessionBundle are resolved with their full info loaded from JSON
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
    template_overrides: dict[str, str | None] = Field(
        default_factory=dict,
        description=(
            'Mapping of glob patterns to provider aliases (or None to suppress) '
            'after resolution. '
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
    fast_lanes: FastLanesSection = Field(
        default_factory=FastLanesSection,
        description=(
            'Fast lane section: dest resolutions and per-lane config. '
            'Inherited directly from `RepolishConfigFile.fast_lanes`.'
        ),
    )
