import warnings
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from repolish.exceptions import ProviderConfigError


class ProviderOverrides(BaseModel):
    """Consolidated container for provider-level overrides.

    This is the single extension point for overriding provider behavior
    from the project configuration. All override types belong here:

    - ``context_merge``: Simple key-value merges into provider context (shallow)
    - ``context_dotted``: Dot-notation overrides for nested context values (deep)
    - ``anchors``: Anchor definitions to override provider defaults
    - ``file_mappings``: Per-file enabled/disabled overrides

    Usage in repolish.yaml::

        providers:
          my-provider:
            cli: my-provider-link
            overrides:
              # Shallow merge: {greeting: 'Hello', name: 'World'}
              context_merge:
                greeting: Hello
                name: World
              # Deep override: nested.key -> value
              context_dotted:
                database.host: localhost
                database.port: 5432
              anchors:
                my_anchor: overridden_value
              # Full options dict
              file_mappings:
                path/to/file.yaml:
                  enabled: false
              # Shortcut: just disable a file
              file_mappings:
                path/to/file.yaml: false
    """

    context_merge: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Simple key-value overrides merged shallow into provider context. '
            'Top-level keys only; nested values replace entirely.'
        ),
    )
    context_dotted: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Dot-notation overrides for nested context values. '
            'Keys use dotted path syntax (e.g., "database.host") for deep access.'
        ),
    )
    anchors: dict[str, str] | None = Field(
        default=None,
        description="Anchor overrides on top of provider's create_anchors output.",
    )
    file_mappings: dict[str, dict[str, Any] | bool] | None = Field(
        default=None,
        description=(
            'Per-file enabled overrides keyed by destination path. '
            'Shortcut: use ``false`` to disable (sets ``enabled: false``). '
            'Full form: dict with ``enabled`` (bool).'
        ),
    )

    @field_validator('file_mappings', mode='before')
    @classmethod
    def normalize_file_mappings(
        cls,
        value: dict[str, dict[str, Any] | bool] | None,
    ) -> dict[str, dict[str, Any] | bool] | None:
        """Normalize file_mappings to support shortcut syntax.

        Allows:
            file_mappings:
              path/to/file.yaml: false    # shortcut for {enabled: false}
              path/to/other.yaml:
                enabled: true
                skip_render: false
        """
        if value is None:
            return value

        normalized: dict[str, dict[str, Any] | bool] = {}
        for path, val in value.items():
            if isinstance(val, bool):
                # Shortcut: false -> {enabled: false}, true -> {enabled: true}
                normalized[path] = {'enabled': val}
            else:
                normalized[path] = val

        return normalized


class ProviderSymlink(BaseModel):
    """Configuration for a provider symlink.

    Internal model used in config resolution and provider info.
    For the decorator API, use the Symlink dataclass from repolish.linker.
    """

    source: Path = Field(
        description='Path relative to provider resources (e.g., "configs/.editorconfig").',
    )
    target: Path = Field(
        description='Path relative to repo root (e.g., ".editorconfig").',
    )

    @field_serializer('source', 'target', when_used='json')
    def _serialize_path(self, value: Path) -> str:
        """Serialize Path to string for JSON output."""
        return value.as_posix()


class ProviderCopy(ProviderSymlink):
    """Configuration for a provider resource copy.

    Identical fields to :class:`ProviderSymlink`; the distinction is
    semantic — the file is physically copied rather than symlinked.
    For the decorator API, use the ResourceCopy dataclass from
    repolish.providers.models.
    """


class ProviderConfig(BaseModel):
    """Configuration for a single provider.

    Users may now specify an optional `context` mapping on a per-provider
    basis; values supplied here are merged into the context produced by the
    provider itself, giving projects the ability to tweak or override provider
    defaults without editing the provider code.  This field is intentionally
    named `context` to mirror the top-level configuration key and keep the
    YAML concise.

    .. deprecated::
        The ``context``, ``context_overrides``, and ``anchors`` fields at the
        top level are deprecated in favor of the consolidated ``overrides``
        field. Legacy fields are still supported but will emit deprecation
        warnings.
    """

    cli: str | None = Field(
        default=None,
        description='CLI command to call for linking (e.g., codeguide-link)',
    )
    provider_root: str | None = Field(
        default=None,
        description=(
            'Path to the directory containing repolish.py and the repolish/ '
            'template tree. Can be combined with cli: if an info file is found '
            'the CLI result takes precedence; otherwise this is used as a fallback.'
        ),
    )
    resources_dir: str | None = Field(
        default=None,
        description=(
            'Root of the provider resources directory inside the project '
            '(e.g. .repolish/mylib/). Typically the parent of provider_root; '
            'may also contain sibling folders such as configs/. '
            'Symlink source paths are resolved relative to this directory. '
            'Falls back to provider_root when not set. Requires provider_root to be set.'
        ),
    )
    symlinks: list[ProviderSymlink] | None = Field(
        default=None,
        description='Symlinks from resources to repo. Use provider defaults with None. Skip symlinks with empty list.',
    )
    copies: list[ProviderCopy] | None = Field(
        default=None,
        description='Copies from resources to repo. Use provider defaults with None. Skip copies with empty list.',
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional overrides to merge into this provider's context after evaluation. "
            'Deprecated: use overrides.context_merge instead.'
        ),
        deprecated='use overrides.context_merge instead.',
    )
    context_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dot-notation overrides to apply to this provider's context (opt-in;"
            ' providers must also be migrated to use). '
            'Deprecated: use overrides.context_dotted instead.'
        ),
        deprecated='use overrides.context_dotted instead.',
    )
    anchors: dict[str, str] | None = Field(
        default=None,
        description=(
            'Optional anchor overrides for this provider. '
            'Merged on top of anchors returned by the provider create_anchors hook. '
            'Deprecated: use overrides.anchors instead.'
        ),
        deprecated='use overrides.anchors instead.',
    )
    overrides: ProviderOverrides | None = Field(
        default=None,
        description='Consolidated container for all provider-level overrides.',
    )

    @model_validator(mode='before')
    @classmethod
    def normalize_legacy_overrides(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize legacy top-level override fields into the overrides container.

        This provides backward compatibility for configs that use the old
        top-level ``context``, ``context_overrides``, and ``anchors`` fields.
        Emits deprecation warnings for each legacy field used.

        Legacy field mapping:
        - ``context`` -> ``overrides.context_merge``
        - ``context_overrides`` -> ``overrides.context_dotted``
        - ``anchors`` -> ``overrides.anchors``
        """
        overrides_data: dict[str, Any] = data.get('overrides') or {}

        cls._migrate_field(
            data,
            overrides_data,
            'context',
            'context_merge',
            'context_merge',
        )
        cls._migrate_field(
            data,
            overrides_data,
            'context_overrides',
            'context_dotted',
            'context_dotted',
        )
        cls._migrate_field(
            data,
            overrides_data,
            'anchors',
            'anchors',
            'anchors',
        )

        if overrides_data:
            data['overrides'] = overrides_data

        return data

    @staticmethod
    def _migrate_field(
        data: dict[str, Any],
        overrides: dict[str, Any],
        old: str,
        new: str,
        target: str,
    ) -> None:
        """Migrate a single legacy field into the overrides container."""
        if old not in data or data[old] is None:
            return
        if new in overrides and overrides[new] is not None:
            return

        warnings.warn(
            f"Provider config field '{old}' at top level is deprecated. Use 'overrides.{target}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        overrides[new] = data[old]

    @model_validator(mode='after')
    def validate_cli_or_provider_root(self) -> 'ProviderConfig':
        """Ensure at least one of cli or provider_root is provided.

        cli and provider_root may coexist: if a provider-info JSON file is
        found at runtime the CLI result takes precedence; provider_root acts
        as a static fallback when no info file is present.
        """
        if self.cli is None and self.provider_root is None:
            msg = 'Either cli or provider_root must be provided'
            raise ProviderConfigError(msg)
        if self.resources_dir is not None and self.provider_root is None:
            msg = 'resources_dir requires provider_root to be set'
            raise ProviderConfigError(msg)
        return self


class ResolvedProviderInfo(BaseModel):
    """Fully resolved provider information for runtime use.

    This combines data from ProviderConfig (YAML) and ProviderInfo (JSON)
    with all paths resolved and validated.

    The `context` field mirrors the top-level project `context` but is
    scoped to a single provider; values supplied here are merged into the
    context captured from the provider during loading.
    """

    alias: str = Field(
        description='Provider alias name used in configuration',
    )
    provider_root: Path = Field(
        description='Fully resolved directory containing repolish.py and the repolish/ template tree.',
    )
    resources_dir: Path = Field(
        description=(
            'Fully resolved root of the linked resources directory. '
            'Equal to provider_root when there is no subdirectory offset; otherwise '
            'the parent that contains provider_root as well as other resource folders '
            'such as configs/.'
        ),
    )
    symlinks: list[ProviderSymlink] = Field(
        default_factory=list,
        description='Additional symlinks to create from provider resources to repo',
    )
    copies: list[ProviderCopy] = Field(
        default_factory=list,
        description='Files to copy from provider resources to repo',
    )
    overrides: ProviderOverrides | None = Field(
        default=None,
        description=(
            'Consolidated container for all provider-level overrides (resolved). '
            'Contains context_merge, context_dotted, anchors, and file_mappings.'
        ),
    )
