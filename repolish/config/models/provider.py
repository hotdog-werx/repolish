from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_serializer, model_validator

from repolish.exceptions import ProviderConfigError


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


class ProviderConfig(BaseModel):
    """Configuration for a single provider.

    Users may now specify an optional `context` mapping on a per-provider
    basis; values supplied here are merged into the context produced by the
    provider itself, giving projects the ability to tweak or override provider
    defaults without editing the provider code.  This field is intentionally
    named `context` to mirror the top-level configuration key and keep the
    YAML concise.
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
    context: dict[str, Any] | None = Field(
        default=None,
        description="Optional overrides to merge into this provider's context after evaluation.",
    )
    context_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dot-notation overrides to apply to this provider's context (opt-in;"
            ' providers must also be migrated to use).'
        ),
    )
    anchors: dict[str, str] | None = Field(
        default=None,
        description=(
            'Optional anchor overrides for this provider. '
            'Merged on top of anchors returned by the provider create_anchors hook.'
        ),
    )

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
    context: dict[str, Any] | None = Field(
        default=None,
        description='Provider-specific context overrides from the project configuration.',
    )
    context_overrides: dict[str, Any] | None = Field(
        default=None,
        description=(
            'Provider-scoped dotted-path overrides; applied after `context` and before global context overrides.'
        ),
    )
    anchors: dict[str, str] | None = Field(
        default=None,
        description=(
            'Provider-scoped anchor overrides from the project configuration. '
            'Merged on top of anchors returned by the provider create_anchors hook.'
        ),
    )
