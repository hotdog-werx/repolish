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
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel, Field


class BaseContext(BaseModel):
    """Minimal, empty context type for providers.

    Providers almost always define their own context model, but when no
    fields are needed this class can be used as a lightweight default.  It
    avoids the awkward requirement that `BaseModel` itself cannot be
    instantiated and keeps callers from having to import Pydantic directly -
    you can `from repolish import BaseContext`.

    Historically many tests and examples simply used `BaseModel` for this
    purpose, which triggered errors and confusion.  `BaseContext` is the
    safer, idiomatic alternative.
    """


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
        tree. May be 'None' for `FileMode.DELETE` mappings.
      - extra_context: optional typed context (Pydantic models allowed).
      - file_mode: optional behavior hint for the destination path.
    """

    source_template: str | None
    extra_context: object | None = None
    file_mode: FileMode = FileMode.REGULAR
    # provider alias that originally supplied the template.  This is not
    # something the provider needs to set; the loader populates it during
    # merging so we can track provenance of conditional/create-only/delete
    # mappings across multiple providers.
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
    # These values may be either a plain dict or a BaseModel instance; the
    # orchestrator will convert them to dicts when merging into the global
    # context.  Keeping the original object lets us pass typed models to
    # provider helpers such as 'create_file_mappings()'.
    provider_contexts: dict[str, object] = Field(
        default_factory=dict,
    )
    # per-provider migration flag: providers that have opted into the new
    # provider-scoped template-context behaviour set this to True
    provider_migrated: dict[str, bool] = Field(default_factory=dict)
    # mapping from a relative template path (POSIX string) to the provider id
    # that supplied the file when staging.  Populated by the builder so the
    # renderer can later look up which provider owns a given template and, in
    # conjunction with 'provider_migrated', decide whether to render using
    # the merged context or the provider's own context.
    template_sources: dict[str, str] = Field(default_factory=dict)


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
InputT = TypeVar('InputT', bound=BaseModel)


# `ProviderEntry` is the object passed to provider hooks such as
# `provide_inputs` and `finalize_context`.  it carries richer metadata
# than the former 3-tuple and uses concise names:
#
# `provider_id` (str) - unique loader-assigned identifier
# `name` (str|None) - canonical name returned by
#     :meth:`Provider.get_provider_name`
# `alias` (str|None) - name under which the provider was registered in the
#     configuration; usually a directory name or config key
# `inst_type` (type|None) - concrete type of the provider instance
# `context` (object) - raw context value, usually a `BaseModel` or dict
# `context_type` (type|None) - class of `context` when it is a
#     `BaseModel`
# `input_type` (type|None) - schema returned by
#     :meth:`Provider.get_inputs_schema` (`None` for providers without inputs)
#
# Only the first and last fields are commonly used; the others exist for
# introspection and tooling.  tuple-like compatibility helpers were removed
# long ago, so callers should access attributes directly.
class ProviderEntry(BaseModel):
    """Metadata for a provider exposed during orchestration.

    `ProviderEntry` replaces the legacy 3-tuple representation.  Fields are
    intentionally named to make their purpose obvious and are short enough to
    be convenient when used in provider hooks.

    Attributes:
    ----------
    provider_id:
        unique identifier (usually the filesystem path) assigned by the loader.
    name:
        canonical name returned by :meth:`Provider.get_provider_name`
        (`None` if the provider instance could not be created).
    alias:
        configuration alias (the key/name used in the repolish.yaml or the
        directory name).  this may differ from `name` when providers
        override their own internal name.
    inst_type:
        the concrete `type` of the provider instance, if any.  this allows
        consumers to dispatch based on implementation class rather than string
        names.
    context:
        raw context object.  this is typed as `object` to support the
        legacy module adapter; after v1 when the adapter is removed this will
        be tightened to `BaseModel`.
        raw context object produced or stored for this provider.
    context_type:
        if `context` is a :class:`pydantic.BaseModel`, this is its class
        object; otherwise `None`.
    input_type:
        the schema returned by :meth:`Provider.get_inputs_schema`, equivalent
        to the third element of the old tuple.  `None` for providers that do
        not accept inputs.
    """

    provider_id: str
    # canonical provider name returned by :meth:`Provider.get_provider_name`
    # (formerly called `alias`).  this is the "/real" name of the
    # provider implementation and may differ from the key used in project
    # configuration.
    name: str | None = None
    # alias as specified in the project configuration file.  for
    # providers created via `create_providers` this will typically equal
    # the directory name or the config key; in many cases it is identical to
    # `provider_id` but having a separate field makes intent clear.
    alias: str | None = None
    inst_type: type[Any] | None = None
    context: object = Field(default_factory=dict)
    context_type: type[BaseModel] | None = None
    input_type: type[BaseModel] | None = None


class Provider(ABC, Generic[ContextT, InputT]):
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

    def provide_inputs(
        self,
        own_context: ContextT,  # noqa: ARG002 - parameter may be unused
        all_providers: list[ProviderEntry],  # noqa: ARG002 - parameter may be unused
        provider_index: int,  # noqa: ARG002 - parameter may be unused
    ) -> list[BaseModel]:
        """Return payload objects that should be sent to other providers.

        The loader calls this hook when it needs outbound data from a
        provider. The implementation should return a sequence of
        :class:`BaseModel` instances; returning raw mappings is only supported
        for legacy module-style providers and will be removed in v1.  The
        orchestration layer routes each item based on the receiving
        provider's input schema (provided via :meth:`get_inputs_schema`).
        Subclasses should override this method to supply whatever
        information is relevant to downstream providers.

        `all_providers` is a list of :class:`ProviderEntry` instances; only
        the `input_type`/`alias` attributes are useful
        for most providers.

        The default implementation returns an empty list.
        """
        return []

    def finalize_context(
        self,
        own_context: ContextT,
        received_inputs: list[InputT],  # noqa: ARG002 - parameter may be unused
        all_providers: list[ProviderEntry],  # noqa: ARG002 - parameter may be unused
        provider_index: int,  # noqa: ARG002 - parameter may be unused
    ) -> ContextT:
        """Optionally apply inputs received from other providers.

        Parameters are:
        - 'own_context': the context object produced by 'create_context()'
          before any inputs are merged.
        - 'received_inputs': list of payloads delivered by other providers
          whose 'get_inputs_schema()' matched the values.
        - 'all_providers': snapshot of every provider the loader knows about.
          each item is a :class:`ProviderEntry` object; providers can inspect
          attributes such as `alias` or `input_type` if
          they need to make context-dependent decisions.  the argument is
          optional and most providers can ignore it entirely.
        - 'provider_index': the position of this provider in the load order.

        Default: return the unmodified `own_context`.
        """
        return own_context

    def get_inputs_schema(self) -> type[InputT] | None:
        """Return the Pydantic model class for this provider's *input* type.

        - If non-'None', other providers may create instances of this class
          and return them from `provide_inputs()` using this
          provider's name as the key.
        - If 'None' (the default) this provider is not eligible to receive
          inputs; calls to `provide_inputs()` may still supply
          values for other recipients.

        This method is primarily used by the loader/orchestrator to perform
        optional runtime validation and to expose the schema for tooling
        (e.g. CLI help).  Providers that override `provide_inputs`
        should usually also override this method so the contract is explicit.
        """
        return None

    # File operations helpers - optional

    def create_file_mappings(
        self,
        context: ContextT,  # noqa: ARG002 - parameter may be unused
    ) -> dict[str, str | TemplateMapping]:
        """Optional: return `file_mappings`-style dict for this provider.

        The merged provider context (a 'ContextT' instance) is passed when
        available.  Providing a typed argument instead of a plain 'dict' makes
        migration to the new class API cleaner and enables IDE autocomplete.
        Default implementation ignores the argument and returns an empty
        mapping.
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


# ---------------------------------------------------------------------------
# Utility functions for provider inputs
# ---------------------------------------------------------------------------


def get_provider_inputs_schema(
    provider_cls: type[Provider[Any, Any]],
    providers: list[Provider[Any, Any]],
) -> type[BaseModel] | None:
    """Return the inputs schema class for any instance of 'provider_cls'.

    This helper walks the *instances* list and uses 'isinstance' to find
    a matching provider; if one is found its 'get_inputs_schema' result is
    returned.  'None' means either no matching provider was loaded or the
    provider declares no inputs.
    """
    for p in providers:
        if isinstance(p, provider_cls):
            return p.get_inputs_schema()
    return None


def get_provider_inputs(
    provider_cls: type[Provider[Any, Any]],
    providers: list[Provider[Any, Any]],
) -> BaseModel | None:
    """Return a new inputs instance for 'provider_cls' or 'None'.

    This mirrors :func:`get_provider_inputs_schema` but also instantiates the
    class.  'provider_cls' must be a provider class and not a string alias.
    If no matching provider is loaded or the provider declares no inputs,
    'None' is returned.
    """
    schema = get_provider_inputs_schema(provider_cls, providers)
    if schema is None:
        return None
    return schema()


# typing helpers for get_provider_context
T = TypeVar('T', bound=BaseModel)


def get_provider_context(
    identifier: type[Provider[T, Any]],
    providers: list[ProviderEntry],
) -> T | None:
    """Return the raw context object for a provider matching `identifier`.

    `identifier` must be a provider class (or subclass thereof). The
    function searches `providers` for the first entry whose `inst_type`
    is a subclass of `identifier` and returns its `context` value.
    """
    # disallow the bare Provider base class; it would match everything
    if identifier is Provider:
        return None

    for entry in providers:
        if entry.inst_type is identifier:
            # type checker can't infer that context matches T, so cast
            return cast('T', entry.context)
    return None
