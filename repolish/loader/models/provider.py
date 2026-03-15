"""Provider base class, entry metadata, and provider utility functions.

Defines the public API for class-based providers:
- :class:`ProviderEntry` — metadata record passed to provider hooks
- :class:`Provider` — ABC base class all class-based providers subclass
- :func:`get_provider_inputs_schema` / :func:`get_provider_inputs` / :func:`get_provider_context`
  — convenience lookup helpers

Type variables :data:`ContextT`, :data:`InputT`, and :data:`T` are exported so
provider authors do not need to import from :mod:`typing` directly.
"""

from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel, Field

from repolish.loader._log import logger
from repolish.loader.models.context import BaseContext, BaseInputs, Symlink
from repolish.loader.models.files import FileMode, TemplateMapping

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
    version: str = ''  # package version; auto-detected by the loader when possible
    package_name: str = ''  # top-level Python package (import name), e.g. "devkit_workspace"
    project_name: str = ''  # distribution name from pyproject.toml [project] name, e.g. "devkit-workspace"

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

    def create_default_symlinks(self) -> list[Symlink]:
        """Optional: return the default symlinks this provider wants created.

        Each :class:`Symlink` has a ``source`` path (relative to the
        provider's ``resources_dir``) and a ``target`` path (relative to the
        project root).

        These defaults can be overridden per-project in ``repolish.yaml``
        via the ``symlinks`` key on the provider entry:

        - Omit ``symlinks`` → call this method and use what it returns.
        - ``symlinks: []`` → skip all symlinks for this provider.
        - Explicit list → use the YAML list; this method is not called.

        Default implementation returns an empty list (no symlinks).
        """
        return []


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


# Unused import kept for FileMode - it is re-exported from this module so
# that code doing `from repolish.loader.models.provider import FileMode`
# continues to work.  The canonical location is repolish.loader.models.files.
__all__ = [
    'ContextT',
    'FileMode',
    'InputT',
    'Provider',
    'ProviderEntry',
    'T',
    '_get_provider_generic_args',
    'get_provider_context',
    'get_provider_inputs',
    'get_provider_inputs_schema',
]
