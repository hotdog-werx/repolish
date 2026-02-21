"""Loader-side Provider base class (incremental, backwards-compatible).

This module introduces a small, typed, abstract base class to guide
implementation of class-based providers. Existing module-style providers
(repolish.py with `create_context()` etc.) remain fully supported; this
class is opt-in and intended to improve discoverability, editor
experience and testing for new providers.

Short example
--------------
from pydantic import BaseModel
from repolish.loader.models import Provider

class MyContext(BaseModel):
    name: str = 'default'

class MyProvider(Provider[MyContext, BaseModel]):
    def get_provider_name(self) -> str:
        return 'my-provider'

    def create_context(self) -> MyContext:
        return MyContext(name='overridden')

Notes:
-----
- Only `get_provider_name()` and `create_context()` are required.
- Optional methods have sensible defaults so subclasses implement only
  the behaviour they need.
- This class is intentionally minimal and lives in the `loader` package
  so migration from module-style providers can be incremental.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path  # noqa: TC003 - used in Providers model with pydantic
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

# --- moved from `loader/types.py` -------------------------------------------------


class Action(str, Enum):
    """Enumeration of possible actions for a path."""

    delete = 'delete'
    keep = 'keep'


class Decision(BaseModel):
    """Typed provenance decision recorded for each path.

    - source: provider identifier (POSIX string)
    - action: Action enum
    """

    source: str
    action: Action


class FileMode(str, Enum):
    """Per-file behavior for a `TemplateMapping`.

    - REGULAR: render and materialize as normal (default)
    - CREATE_ONLY: treat the destination as create-only (never overwrite existing)
    - DELETE: mark the destination for deletion (no source template required)
    """

    REGULAR = 'regular'
    CREATE_ONLY = 'create_only'
    DELETE = 'delete'


@dataclass(frozen=True)
class TemplateMapping:
    """Typed representation for a per-file `file_mappings` entry.

    Fields:
      - source_template: relative path to the template under the merged template
        tree. May be ``None`` for `FileMode.DELETE` mappings.
      - extra_context: optional typed context (Pydantic models allowed).
      - file_mode: optional behavior hint for the destination path.
    """

    source_template: str | None
    extra_context: object | None = None
    file_mode: FileMode = FileMode.REGULAR
    source_provider: str | None = None


class Providers(BaseModel):
    """Structured provider contributions collected from template modules.

    - context: merged cookiecutter context
    - anchors: merged anchors mapping
    - delete_files: list of Paths representing files to delete
    - file_mappings: dict mapping destination paths to source paths in template
    - create_only_files: list of Paths for files that should only be created if they don't exist

    Validation: `file_mappings` entries are validated by Pydantic so downstream
    code can safely rely on typed values instead of performing defensive
    runtime checks.
    """

    context: dict[str, object] = Field(default_factory=dict)
    anchors: dict[str, str] = Field(default_factory=dict)
    delete_files: list[Path] = Field(default_factory=list)
    # destination -> source OR TemplateMapping
    file_mappings: dict[str, str | TemplateMapping] = Field(
        default_factory=dict,
    )
    create_only_files: list[Path] = Field(default_factory=list)
    # provenance mapping: posix path -> list of Decision instances
    delete_history: dict[str, list[Decision]] = Field(default_factory=dict)
    # provider-specific contexts captured during provider evaluation
    provider_contexts: dict[str, dict[str, object]] = Field(
        default_factory=dict,
    )
    # per-provider migration flag: providers that have opted into the new
    # provider-scoped template-context behaviour set this to True
    provider_migrated: dict[str, bool] = Field(default_factory=dict)


class Accumulators(BaseModel):
    """Internal accumulator used during two-phase provider merging.

    This mirrors the runtime mutable containers used by the orchestrator to
    collect anchors, file mappings, create-only sets, delete sets and the
    provenance history before converting to the public `Providers` model.
    """

    merged_anchors: dict[str, str]
    merged_file_mappings: dict[str, str | TemplateMapping]
    create_only_set: set[Path]
    delete_set: set[Path]
    history: dict[str, list[Decision]]


# --- end moved types ------------------------------------------------------------

ContextT = TypeVar('ContextT', bound=BaseModel)
InputsT = TypeVar('InputsT', bound=BaseModel)


class Provider(ABC, Generic[ContextT, InputsT]):
    """Abstract base class for class-based providers.

    Subclass this when implementing a new provider. Only `get_provider_name`
    and `create_context` are required; other methods are optional and have
    default implementations to preserve backwards compatibility with the
    existing loader behaviour.
    """

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the canonical provider identifier (alias/library-name)."""

    @abstractmethod
    def create_context(self) -> ContextT:
        """Create and return this provider's context model."""

    def collect_provider_inputs(
        self,
        _own_context: ContextT,
        _all_providers: list[tuple[str, Any]],
        _provider_index: int,
    ) -> dict[str, Any]:
        """Optionally return inputs to send to other providers.

        Default: no inputs (empty dict).
        """
        return {}

    def finalize_context(
        self,
        _own_context: ContextT,
        _received_inputs: list[InputsT],
        _all_providers: list[tuple[str, Any]],
        _provider_index: int,
    ) -> ContextT:
        """Optionally apply inputs received from other providers.

        Default: return the unmodified `own_context`.
        """
        return _own_context

    def get_inputs_schema(self) -> type[InputsT] | None:
        """Return the Pydantic model type accepted as inputs by this provider.

        Default: `None` meaning this provider does not accept inputs.
        """
        return None

    # File operations helpers - optional

    def create_file_mappings(
        self,
        _ctx: dict[str, object] | None = None,
    ) -> dict[str, str | TemplateMapping]:
        """Optional: return `file_mappings`-style dict for this provider.

        Return a mapping dest_path -> source where `source` is either a
        `str` (template path) or a `TemplateMapping` instance for structured
        per-file behaviour. Default: no mappings (empty dict).
        """
        return {}

    def create_anchors(
        self,
        _ctx: dict[str, object] | None = None,
    ) -> dict[str, str]:
        """Optional: return anchors mapping for this provider.

        Default: no anchors (empty dict). Subclasses may accept an optional
        context argument to make decisions based on the merged context.
        """
        return {}
