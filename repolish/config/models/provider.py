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
    directory: str | None = Field(
        default=None,
        description=(
            'Path to provider resources (either a directory or location '
            'discovered by CLI). Should point at the template root containing '
            '`repolish.py`.'
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
    target_dir: Path = Field(
        description='Fully resolved directory where provider resources are linked (must contain repolish.py).',
    )
    resources_dir: Path = Field(
        description=(
            'Fully resolved root of the linked resources directory. '
            'Equal to target_dir when templates_dir is empty; otherwise the parent '
            'that contains both the templates subdirectory and other resource folders '
            'such as configs/.'
        ),
    )
    library_name: str | None = Field(
        default=None,
        description='Name of the provider library (optional)',
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
