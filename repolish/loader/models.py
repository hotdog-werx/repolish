"""Loader-side Provider base class and shared data models.

This module defines the base class for class-based providers (it is no
longer strictly abstract) as well as all shared data models used by the
loader and orchestrator.

Short example
--------------
from pydantic import BaseModel
from repolish.loader.models import Provider

class MyContext(BaseModel):
    name: str = 'default'

class MyProvider(Provider[MyContext, BaseModel]):
    def create_context(self) -> MyContext:
        return MyContext(name='overridden')

Notes:
-----
- Only `create_context()` is required; all other methods are optional.
- Optional methods have sensible defaults so subclasses implement only
  the behaviour they need.
"""

from __future__ import annotations

import datetime
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel, Field

from repolish.loader._log import logger


class GithubRepo(BaseModel):
    """Model representing a GitHub repository identifier.

    Historically the global context exposed ``repo_owner`` and
    ``repo_name`` as two separate fields.  They have been consolidated into a
    single nested object here to make the structure easier to work with in
    templates and to allow additional repository metadata in the future.
    """

    owner: str = 'UnknownOwner'
    name: str = 'UnknownRepo'


class GlobalContext(BaseModel):
    """Globally-available values injected into every provider context.

    By default the loader only populates the GitHub repository information
    (read from the ``origin`` remote).  Additional keys may be added in
    future releases.  The value is exposed to templates as ``repolish`` (see
    :mod:`docs.configuration.context` for details) and the typed field is
    available to class-based providers that inherit from :class:`BaseContext`.

    ``GlobalContext`` is intentionally trivial so consumer code can import
    it directly when typing provider contexts; providers that don't declare
    a subclass of :class:`~repolish.loader.models.BaseContext` simply ignore
    it.
    """

    repo: GithubRepo = Field(default_factory=GithubRepo)
    # `year` is intentionally coarse-grained; it's useful for license
    # headers and other boilerplate that should not require manual updates
    # when the calendar rolls over.  The value is computed when the model is
    # instantiated so repeated loader runs within the same year remain
    # consistent yet automatically advance at New Year's.
    year: int = Field(
        default_factory=lambda: datetime.datetime.now(
            datetime.UTC,
        ).year,
    )


def get_global_context() -> GlobalContext:
    """Return a model populated from the current repository settings.

    The implementation is intentionally forgiving; any failure to extract
    information (for example when not running inside a git repository) is
    swallowed and the returned object will simply have default values.  The
    loader calls this during startup and injects the result directly into
    every provider context so the ``repolish`` namespace is available to all
    providers and templates.
    """
    # imported locally to avoid a circular dependency when the loader tests
    # import the helper without needing the providers package.
    from repolish.providers import git  # noqa: PLC0415 - local import avoids circular

    try:
        owner, name = git.get_owner_repo()
    except Exception:  # noqa: BLE001
        owner = name = 'Unknown'
    # explicitly compute the year here as well; this mirrors the default
    # factory and ensures callers that bypass the default still receive a
    # sensible value.
    return GlobalContext(
        repo=GithubRepo(owner=owner, name=name),
        year=datetime.datetime.now(datetime.UTC).year,
    )


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

    repolish: GlobalContext = Field(default_factory=GlobalContext)


class BaseInputs(BaseModel):
    """Base class for provider inputs.

    This is not strictly necessary since providers can declare any Pydantic
    model as their input schema, but it provides a convenient shared parent
    for type checking and tooling.  Providers that declare an input schema
    but don't need any fields can use this empty class as a default.
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
    - KEEP: explicitly cancel a delete scheduled by an earlier provider
    """

    REGULAR = 'regular'
    CREATE_ONLY = 'create_only'
    DELETE = 'delete'
    KEEP = 'keep'


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


@dataclass(frozen=True)
class FileRecord:
    """Resolved disposition for a single managed file.

    `path` is the POSIX destination path.
    `mode` is the effective FileMode (REGULAR, CREATE_ONLY, DELETE, KEEP).
    `owner` is the config alias of the provider that controls this file,
    or 'config' for entries driven by config.delete_files.
    """

    path: str
    mode: FileMode
    owner: str


class Providers(BaseModel):
    """Structured provider contributions collected from all loaded providers.

    - anchors: merged anchors mapping
    - delete_files: list of Paths representing files to delete
    - file_mappings: dict mapping destination paths to source paths in template
    - create_only_files: list of Paths for files that should only be created if they don't exist
    - provider_contexts: typed per-provider context objects; use these (not a
      flat dict) to access provider-specific data during rendering.

    Validation: `file_mappings` entries are validated by Pydantic so downstream
    code can safely rely on typed values instead of performing defensive
    runtime checks.
    """

    anchors: dict[str, str] = Field(default_factory=dict)
    delete_files: list[Path] = Field(default_factory=list)
    # destination -> source OR TemplateMapping
    file_mappings: dict[str, str | TemplateMapping] = Field(
        default_factory=dict,
    )
    create_only_files: list[Path] = Field(default_factory=list)
    # provenance mapping: posix path -> list of Decision instances
    delete_history: dict[str, list[Decision]] = Field(default_factory=dict)
    # provider-specific contexts captured during provider evaluation.
    # These are the authoritative typed objects for each provider; the
    # renderer looks up the owning provider's context here when processing
    # per-file template mappings (e.g. 'create_file_mappings()').
    provider_contexts: dict[str, BaseContext] = Field(
        default_factory=dict,
    )
    # mapping from a relative template path (POSIX string) to the provider id
    # that supplied the file when staging.  Populated by the builder so the
    # renderer can later look up which provider owns a given template and
    # decide whether to use the provider's own context.
    template_sources: dict[str, str] = Field(default_factory=dict)
    # template paths that providers explicitly suppressed via a None mapping
    # in create_file_mappings.  These are excluded from auto-staging so the
    # builder does not copy them to the consumer's working tree.
    suppressed_sources: set[str] = Field(default_factory=set)
    # unified file disposition list; populated by `build_file_records` after
    # staging is complete.  empty until that function is called.
    file_records: list[FileRecord] = Field(default_factory=list)


def _records_from_template_sources(
    template_sources: dict[str, str],
    create_only_posix: set[str],
    pid_to_alias: dict[str, str],
) -> dict[str, FileRecord]:
    """Return FileRecord entries from staged template sources."""
    files: dict[str, FileRecord] = {}
    for rel_path, pid in template_sources.items():
        owner = pid_to_alias.get(pid, pid)
        mode = FileMode.CREATE_ONLY if rel_path in create_only_posix else FileMode.REGULAR
        files[rel_path] = FileRecord(path=rel_path, mode=mode, owner=owner)
    return files


def _records_from_file_mappings(
    file_mappings: dict[str, str | TemplateMapping],
    pid_to_alias: dict[str, str],
) -> dict[str, FileRecord]:
    """Return FileRecord entries from explicit file_mappings."""
    files: dict[str, FileRecord] = {}
    for dest, src in file_mappings.items():
        if isinstance(src, TemplateMapping):
            raw_pid = src.source_provider or ''
            owner = pid_to_alias.get(raw_pid, raw_pid or 'unknown')
            files[dest] = FileRecord(path=dest, mode=src.file_mode, owner=owner)
        else:
            files[dest] = FileRecord(
                path=dest,
                mode=FileMode.REGULAR,
                owner='unknown',
            )
    return files


def _records_from_delete_files(
    delete_files: list[Path],
    delete_history: dict[str, list[Decision]],
    pid_to_alias: dict[str, str],
    config_pid: str,
) -> dict[str, FileRecord]:
    """Return FileRecord entries for paths scheduled for deletion."""
    files: dict[str, FileRecord] = {}
    for rel in delete_files:
        path_str = rel.as_posix()
        decisions = delete_history.get(path_str, [])
        if decisions:
            last_src = decisions[-1].source
            owner = 'config' if last_src == config_pid else pid_to_alias.get(last_src, last_src)
        else:
            owner = 'unknown'
        files[path_str] = FileRecord(
            path=path_str,
            mode=FileMode.DELETE,
            owner=owner,
        )
    return files


def build_file_records(
    providers: Providers,
    pid_to_alias: dict[str, str],
    config_pid: str,
) -> list[FileRecord]:
    """Build the unified file disposition list from all provider contributions.

    Call once after staging (when `template_sources` is populated).  The
    result is stored on `providers.file_records` so downstream helpers can
    read a single authoritative source instead of recombining multiple fields.

    Ownership rules:
    - regular/create_only: driven by `template_sources`
    - mapping modes: taken from `TemplateMapping.file_mode`
    - delete: last `Decision` in `delete_history`; source == config_pid -> owner 'config'
    """
    create_only_posix = {p.as_posix() for p in providers.create_only_files}
    files: dict[str, FileRecord] = {}
    files.update(
        _records_from_template_sources(
            providers.template_sources,
            create_only_posix,
            pid_to_alias,
        ),
    )
    files.update(
        _records_from_file_mappings(providers.file_mappings, pid_to_alias),
    )
    files.update(
        _records_from_delete_files(
            providers.delete_files,
            providers.delete_history,
            pid_to_alias,
            config_pid,
        ),
    )
    return sorted(files.values(), key=lambda r: r.path)


@dataclass
class Accumulators:
    """Mutable workspace used while collecting contributions from all providers.

    `_collect_provider_contributions` iterates over every loaded provider,
    calls `create_anchors` and `create_file_mappings`, and accumulates the
    results here.  The fields are written into a `Providers` instance once
    collection is complete.

    `merged_anchors` aggregates the per-provider anchor dicts: each call to
    `create_anchors()` can contribute new keys; later providers win on
    conflicts.  All fields default to empty so callers can construct with
    `Accumulators()`.
    """

    merged_anchors: dict[str, str] = field(default_factory=dict)
    merged_file_mappings: dict[str, str | TemplateMapping] = field(
        default_factory=dict,
    )
    create_only_set: set[Path] = field(default_factory=set)
    delete_set: set[Path] = field(default_factory=set)
    history: dict[str, list[Decision]] = field(default_factory=dict)
    # destination paths that providers explicitly mapped to None — these
    # should not be auto-staged even though no file_mappings entry exists.
    suppressed_sources: set[str] = field(default_factory=set)


# --- end moved types ------------------------------------------------------------

# Type variable for provider context models.  We intentionally
# bind this to :class:`BaseContext` so that type checkers will flag
# any provider whose ``create_context`` returns a plain ``BaseModel``.
# The global namespace is stored in ``GlobalContext`` and is only
# available when the context inherits from ``BaseContext``; binding the
# type variable prevents accidental omission.
ContextT = TypeVar('ContextT', bound=BaseContext)
InputT = TypeVar('InputT', bound=BaseModel)


def _get_provider_generic_args(cls: type) -> tuple[type | None, type | None]:
    """Return (context_cls, input_cls) extracted from ``cls`` generics.

    Inspects ``__orig_bases__`` on the class and returns the first and
    second type arguments from the parameterized ``Provider`` base if
    present.  Missing values are returned as ``None``.  This helper is used
    by ``Provider.create_context`` and ``Provider.get_inputs_schema`` so
    the inference logic is centralised and easier to test.
    """
    from typing import get_args, get_origin  # noqa: PLC0415 - used only here

    bases = getattr(cls, '__orig_bases__', ())
    if not bases:
        return None, None
    base = bases[0]
    if get_origin(base) is not Provider:
        return None, None
    args = get_args(base)
    ctx = args[0] if len(args) >= 1 else None
    inp = args[1] if len(args) >= 2 else None
    return ctx, inp


# `ProviderEntry` is the object passed to provider hooks such as
# `provide_inputs` and `finalize_context`.  it carries richer metadata
# than the former 3-tuple and uses concise names:
#
# `provider_id` (str) - unique loader-assigned identifier
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
    alias:
        configuration alias (the key/name used in the repolish.yaml or the
        directory name).  this may differ from `name` when providers
        override their own internal name.
    inst_type:
        the concrete `type` of the provider instance, if any.  this allows
        consumers to dispatch based on implementation class rather than string
        names.
    context:
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
    """Base class for class-based providers.

    Subclass this when implementing a new provider.  Prior to 0.?? the
    class was *abstract* and required every subclass to implement
    ``create_context``; in practice most implementations simply returned a
    default-constructed Pydantic model.  The default implementation now
    attempts to infer the context type from the generic arguments and
    instantiate it automatically, allowing new providers to omit the
    boilerplate unless custom initialization is required.

    Only ``create_context`` is effectively required; all other methods are
    optional and have sensible defaults so consumers only implement the
    behaviour they actually need.

    Attributes:
        templates_root: Absolute path to the directory containing this
            provider's ``repolish.py`` and templates.  Injected by the
            repolish loader before any hooks are called; use it inside any
            method to discover template files dynamically, e.g.::

                list((self.templates_root / '.github' / 'workflows').glob('*.yaml'))
    """

    templates_root: Path = Path()
    alias: str = ''  # config key assigned by the loader before any hooks run

    def create_context(self) -> ContextT:
        """Return this provider's initial context object.

        The default implementation looks at the subclass' generic
        parameters and calls the first type argument without any parameters.
        Because nearly all providers are declared like
        ``class Foo(Provider[SomeContext, SomeInput])`` this succeeds without
        any additional work.  If we cannot infer a usable type or if
        instantiation fails we simply return a bare :class:`BaseContext`.
        Errors are logged rather than raised so provider loading can
        continue; authors who need a real context should override the
        method themselves.

        Providers that need to pass arguments to their context constructor
        or otherwise perform nontrivial setup should still override this
        method explicitly.  The returned object *must* inherit from
        :class:`BaseContext` so the loader can merge the global ``repolish``
        data into it.
        """
        # reuse helper to obtain generic args
        ctx_cls, _ = _get_provider_generic_args(self.__class__)
        if ctx_cls is None or not isinstance(ctx_cls, type) or not issubclass(ctx_cls, BaseContext):
            logger.warning(
                'provider_context_inference_failed',
                provider=self.__class__.__name__,
            )
            return BaseContext()  # type: ignore[return-value]

        try:
            return ctx_cls()  # type: ignore[return-value]
        except Exception as exc:  # noqa: BLE001 - we log and continue
            logger.warning(
                'provider_context_instantiation_failed',
                provider=self.__class__.__name__,
                error=str(exc),
            )
            return BaseContext()  # type: ignore[return-value]

    def provide_inputs(
        self,
        own_context: ContextT,  # noqa: ARG002 - parameter may be unused
        all_providers: list[ProviderEntry],  # noqa: ARG002 - parameter may be unused
        provider_index: int,  # noqa: ARG002 - parameter may be unused
    ) -> list[BaseInputs]:
        """Return payload objects that should be sent to other providers.

        The loader calls this hook when it needs outbound data from a
        provider. The implementation should return a sequence of
        :class:`BaseInputs` instances; returning raw mappings is only supported
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

        The loader uses this schema to route payloads emitted by other
        providers' ``provide_inputs`` calls.  Historically every
        provider had to implement this method, even when the declared
        type was nothing more than ``BaseInputs``.  The default
        implementation now inspects the second generic argument and
        returns it if it is a subclass of :class:`BaseInputs` other than
        ``BaseInputs`` itself.  This lets simple providers omit the
        boilerplate entirely.

        If inference fails or the argument is the generic ``BaseInputs``
        type ``None`` is returned, meaning the provider does not
        declare a specific input schema.

        Providers that need a nonstandard schema or that return values of
        a different type should continue to override this method.
        """
        # use helper to fetch both parameters
        _, inp_cls = _get_provider_generic_args(self.__class__)
        if inp_cls is None:
            return None
        if isinstance(inp_cls, type) and issubclass(inp_cls, BaseInputs) and inp_cls is not BaseInputs:
            return inp_cls
        return None

    # File operations helpers - optional

    def create_file_mappings(
        self,
        context: ContextT,  # noqa: ARG002 - parameter may be unused
    ) -> dict[str, str | TemplateMapping | None]:
        """Optional: return `file_mappings`-style dict for this provider.

        The merged provider context (a 'ContextT' instance) is passed when
        available.  Use ``self.templates_root`` to discover template files
        dynamically, e.g.::

            list((self.templates_root / '.github' / 'workflows').glob('*.yaml'))

        Default implementation returns an empty mapping.
        """
        return {}

    def create_anchors(
        self,
        context: ContextT,  # noqa: ARG002 - parameter may be unused
    ) -> dict[str, str]:
        """Optional: return anchors mapping for this provider.

        The provider's own context object is passed so implementations can
        make decisions based on it.  Default: no anchors (empty dict).
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
# `T` represents the *context* type returned by a provider entry.  it
# must inherit from `BaseContext` so callers can safely access the
# ``repolish`` attribute on the result.
T = TypeVar('T', bound=BaseContext)


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
