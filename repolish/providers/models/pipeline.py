"""Pipeline model definitions: options and dry-run result.

These models are the input/output contracts for the provider pipeline:

- `PipelineOptions` — runtime parameters passed to the pipeline (overrides,
  alias map, global context, dry-run flag, extra entries and inputs for
  cross-session routing)
- `DryRunResult` — data returned when `PipelineOptions.dry_run` is `True`;
  carries contexts and emitted inputs without writing any files
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from repolish.providers.models.context import (
    BaseContext,
    BaseInputs,
    GlobalContext,
)

if TYPE_CHECKING:
    from repolish.providers.models.provider import ProviderEntry


@dataclass(frozen=True)
class PipelineOptions:
    """Typed container for optional runtime parameters passed to the provider pipeline.

    All fields are optional and have sensible defaults. Callers that only need
    the defaults — e.g. simple standalone runs — can pass `PipelineOptions()`
    without customisation.
    """

    context_overrides: dict[str, object] | None = None
    """Dot-notation overrides applied globally to all provider contexts after creation."""
    provider_overrides: dict[str, dict[str, object]] | None = None
    """Per-provider dot-notation overrides keyed by provider alias."""
    alias_map: dict[str, str] | None = None
    """Mapping from provider_id (filesystem path key) to config alias."""
    global_context: GlobalContext = field(default_factory=GlobalContext)
    """Repo-level globals injected into every provider context."""
    dry_run: bool = False
    """When `True`, skip `collect_provider_contributions` and return a `DryRunResult`."""
    extra_provider_entries: list[ProviderEntry] | None = None
    """Provider entries from member sessions injected into the root session pass."""
    extra_inputs: list[BaseInputs] | None = None
    """Emitted inputs from member sessions injected into the root session routing pool."""
    anchor_overrides: dict[str, dict[str, str]] | None = None
    """Per-provider anchor overrides keyed by provider_id (posix path). Applied on top of
    each provider's create_anchors() output before merging into the session anchors."""


@dataclass
class DryRunResult:
    """Data returned by the pipeline when `PipelineOptions.dry_run` is `True`.

    Captures everything produced during context creation and input exchange,
    but omits the file-contribution phase so no filesystem state is modified.
    The coordinator uses this to carry member-session data into the root session.
    """

    provider_contexts: dict[str, BaseContext]
    """Finalized context objects keyed by provider_id."""
    all_providers_list: list[ProviderEntry]
    """Full provider registry built during this pass (local + any injected extras)."""
    emitted_inputs: list[BaseInputs]
    """Flat list of all inputs emitted by all providers before routing."""
