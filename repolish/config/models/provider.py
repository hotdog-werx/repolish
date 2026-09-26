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
from repolish.providers.models.files import FileMappingOptions


class ProviderOverrides(BaseModel):
    """Consolidated container for provider-level overrides.

    This is the single extension point for overriding provider behavior
    from the project configuration. All override types belong here:

    - ``context_merge``: Simple key-value merges into provider context (shallow)
    - ``context_dotted``: Dot-notation overrides for nested context values (deep)
    - ``anchors``: Anchor definitions to override provider defaults
    - ``file_mappings``: Per-file enabled/disabled overrides
    - ``copies``: Per-copy enabled/disabled overrides keyed by target path

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
              # Stop copying one resource so the project owns the file
              copies:
                dprint.json: false
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
    file_mappings: dict[str, FileMappingOptions] | None = Field(
        default=None,
        description=(
            'Per-file options keyed by destination path. '
            'Shortcut: use ``false`` to disable (sets ``enabled: false``). '
            'Full form: dict with ``enabled``, ``priority``, ``skip_render`` fields.'
        ),
    )
    copies: dict[str, bool] | None = Field(
        default=None,
        description=(
            'Per-copy enabled flags keyed by target path (relative to repo root). '
            'Set an entry to ``false`` to stop repolish copying that resource so '
            'the project can own the file outright. Unlike ``paused_files`` this '
            'is permanent and silent. Applies on top of both provider-declared '
            'default copies and an explicit ``copies`` list.'
        ),
    )
    validators: dict[str, dict[str, bool] | bool] | None = Field(
        default=None,
        description=(
            'Per-file validator toggles keyed by destination path. '
            'Example: {"config.toml": {"lint": false, "schema": true}}.'
        ),
    )
    insertions: dict[str, dict[str, bool] | bool] | None = Field(
        default=None,
        description=(
            'Per-file insertion toggles keyed by destination path. '
            'Example: {"README.md": {"render-year": false}}. '
            'Use {"README.md": false} to disable all insertions for a file.'
        ),
    )
    insertions_extend_files: list[str] | None = Field(
        default=None,
        description=(
            "Additional destination paths that are allowed to use this provider's "
            'insertion registry. This extends provider-declared insertion targets '
            'without modifying provider code.'
        ),
    )

    @field_validator('file_mappings', mode='before')
    @classmethod
    def normalize_file_mappings(
        cls,
        value: dict[str, dict[str, Any] | bool] | None,
    ) -> dict[str, dict[str, Any]] | None:
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

        normalized: dict[str, dict[str, Any]] = {}
        for path, val in value.items():
            if isinstance(val, bool):
                # Shortcut: false -> {enabled: false}, true -> {enabled: true}
                normalized[path] = {'enabled': val}
            else:
                normalized[path] = val

        return normalized

    @field_validator('validators', mode='before')
    @classmethod
    def normalize_validators(
        cls,
        value: dict[str, dict[str, bool] | bool] | None,
    ) -> dict[str, dict[str, bool]] | None:
        """Normalize validator overrides to a dict of enabled flags."""
        if value is None:
            return value
        normalized: dict[str, dict[str, bool]] = {}
        for path, val in value.items():
            if isinstance(val, bool):
                normalized[path] = {'enabled': val}
            elif isinstance(val, dict):
                normalized[path] = {name: bool(enabled) for name, enabled in val.items()}
        return normalized

    @field_validator('insertions', mode='before')
    @classmethod
    def normalize_insertions(
        cls,
        value: dict[str, dict[str, bool] | bool] | None,
    ) -> dict[str, dict[str, bool]] | None:
        """Normalize insertion overrides to a dict of enabled flags."""
        if value is None:
            return value
        normalized: dict[str, dict[str, bool]] = {}
        for path, val in value.items():
            if isinstance(val, bool):
                normalized[path] = {'enabled': val}
            elif isinstance(val, dict):
                normalized[path] = {name: bool(enabled) for name, enabled in val.items()}
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


class ModuleProviderConfig(BaseModel):
    """An installed Python module that packages provider resources.

    The in-process alternative to a linker CLI: repolish locates the module
    with :func:`importlib.util.find_spec`, links its packaged resources under
    ``.repolish/<library-name>/``, and records the same provider-info file a
    CLI registration writes. When both ``module`` and ``cli`` are configured,
    the module path runs first and the CLI is only consulted as a fallback.

    The layout fields mirror the ``resource_linker`` decorator defaults and
    are package-relative (resolved against the module's install location,
    unlike the project-local ``provider_root``/``resources_dir`` fields on
    :class:`ProviderConfig`).

    Usage in repolish.yaml, plain or mapping form::

        providers:
          short-name:
            module: devkit.workspace
          other:
            module:
              name: devkit.workspace
              resources_dir: src/resources
              provider_root: pkg-templates
    """

    name: str = Field(
        description='Importable dotted module name of the provider package (e.g. devkit.workspace).',
    )
    resources_dir: str = Field(
        default='resources',
        description='Resources directory relative to the package root (default: resources).',
    )
    provider_root: str = Field(
        default='templates',
        description=(
            'Subdirectory within resources_dir where repolish.py and the template tree live (default: templates).'
        ),
    )


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

    module: ModuleProviderConfig | None = Field(
        default=None,
        description=(
            'Installed Python module that packages the provider resources '
            '(e.g. devkit.workspace). Takes precedence over cli: the module '
            'is linked in-process and the CLI is only used as a fallback. '
            'Either a plain module name or a mapping with name/resources_dir/'
            'provider_root layout overrides.'
        ),
    )
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

    @field_validator('module', mode='before')
    @classmethod
    def normalize_module(
        cls,
        value: object,
    ) -> ModuleProviderConfig | None:
        """Normalize the ``module`` field to :class:`ModuleProviderConfig`.

        Accepts the plain YAML form (``module: devkit.workspace``) and the
        mapping form with layout overrides, so downstream code only ever sees
        the normalized model.
        """
        if value is None or isinstance(value, ModuleProviderConfig):
            return value
        if isinstance(value, str):
            return ModuleProviderConfig(name=value)
        if isinstance(value, dict):
            return ModuleProviderConfig.model_validate(value)
        msg = f'module must be a string or a mapping, got {type(value).__name__}'
        raise ProviderConfigError(msg)

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
        raw_overrides = data.get('overrides')

        # Convert ProviderOverrides instance to dict for merging
        if isinstance(raw_overrides, ProviderOverrides):
            overrides_data = {
                'context_merge': raw_overrides.context_merge,
                'context_dotted': raw_overrides.context_dotted,
                'anchors': raw_overrides.anchors,
                'file_mappings': raw_overrides.file_mappings,
                'copies': raw_overrides.copies,
                'validators': raw_overrides.validators,
                'insertions': raw_overrides.insertions,
                'insertions_extend_files': raw_overrides.insertions_extend_files,
            }
        else:
            overrides_data = dict(raw_overrides) if raw_overrides else {}

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
        """Ensure at least one of module, cli, or provider_root is provided.

        The three may coexist; precedence at runtime is module, then cli,
        then provider_root as a static fallback.
        """
        if self.module is None and self.cli is None and self.provider_root is None:
            msg = 'One of module, cli, or provider_root must be provided'
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
