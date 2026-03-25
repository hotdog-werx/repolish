"""Provider base class, entry metadata, and provider utility functions.

Defines the public API for class-based providers:
- :class:`ModeHandler` — base class for mode-scoped provider behavior
- :class:`ProviderEntry` — metadata record passed to provider hooks
- :class:`Provider` — ABC base class all class-based providers subclass
- :func:`get_provider_inputs_schema` / :func:`get_provider_inputs` / :func:`get_provider_context`
  — convenience lookup helpers

Type variables :data:`ContextT`, :data:`InputT`, and :data:`T` are exported so
provider authors do not need to import from :mod:`typing` directly.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel, Field

from repolish.providers._log import logger
from repolish.providers.models.context import BaseContext, BaseInputs, Symlink
from repolish.providers.models.files import FileMode, TemplateMapping

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


class ModeHandler(Generic[ContextT, InputT]):
    """Base class for mode-scoped provider behavior.

    Subclass to handle behavior for a single workspace mode (``root``,
    ``member``, or ``standalone``).  Each method has the same no-op default
    as :class:`Provider`; only override what the mode actually needs.

    Attach handlers to a :class:`Provider` subclass via optional class
    attributes::

        class WorkspaceProvider(Provider[WorkspaceContext, WorkspaceInputs]):
            root_mode = RootModeHandler
            member_mode = MemberModeHandler
            # standalone_mode not set → falls back to the no-op defaults

    When repolish calls a hook it checks whether a handler is registered for
    the current workspace mode and delegates to it.  Providers that override a
    hook *directly* on the :class:`Provider` subclass always take priority —
    mode handlers are only reachable via the base class defaults.

    Type parameters must match the enclosing :class:`Provider` so that the
    type checker enforces context/input consistency across all three roles.

    Attributes:
        templates_root: Path to the mode overlay directory
            (``provider_root/{mode}/``).  Set by :func:`call_provider_method`
            before any hook is called.  Use it to discover mode-specific
            template files dynamically, e.g.::

                list(self.templates_root.glob('.github/workflows/*.yaml'))

        alias, version, package_name, project_name: Copied from the enclosing
            :class:`Provider` instance at handler instantiation time.
    """

    # NOTE: templates_root is mode-dependent — call_provider_method scopes it to
    # ``provider_root/{mode}/`` rather than copying the provider value directly.
    # If you add another attribute that requires mode-specific derivation, add a
    # corresponding special case in the copy loop inside call_provider_method.
    templates_root: Path = Path()
    alias: str = ''
    version: str = ''
    package_name: str = ''
    project_name: str = ''

    def provide_inputs(
        self,
        opt: ProvideInputsOptions[ContextT],  # noqa: ARG002 - unused in base implementation
    ) -> list[InputT]:
        """See :meth:`Provider.provide_inputs`."""
        return []

    def finalize_context(
        self,
        opt: FinalizeContextOptions[ContextT, InputT],
    ) -> ContextT:
        """See :meth:`Provider.finalize_context`."""
        return opt.own_context

    def create_file_mappings(
        self,
        context: ContextT,  # noqa: ARG002 - unused in base implementation
    ) -> dict[str, str | TemplateMapping | None]:
        """See :meth:`Provider.create_file_mappings`."""
        return {}

    def create_anchors(
        self,
        context: ContextT,  # noqa: ARG002 - unused in base implementation
    ) -> dict[str, str]:
        """See :meth:`Provider.create_anchors`."""
        return {}

    def create_default_symlinks(
        self,
        context: ContextT,  # noqa: ARG002 - unused in base implementation
    ) -> list[Symlink]:
        """See :meth:`Provider.create_default_symlinks`."""
        return []


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


@dataclass
class ProvideInputsOptions(Generic[ContextT]):
    """Options bundle passed to :meth:`Provider.provide_inputs` and :meth:`ModeHandler.provide_inputs`.

    Replaces the former separate ``own_context``, ``all_providers``, and
    ``provider_index`` parameters.  Access only the fields you need; unused
    ones require no ``noqa`` comment.

    Attributes:
        own_context: This provider's current context object.
        all_providers: Snapshot of every provider the loader knows about.
        provider_index: Position of this provider in the load order.
    """

    own_context: ContextT
    all_providers: list[ProviderEntry]
    provider_index: int


@dataclass
class FinalizeContextOptions(Generic[ContextT, InputT]):
    """Options bundle passed to :meth:`Provider.finalize_context` and :meth:`ModeHandler.finalize_context`.

    Replaces the former separate ``own_context``, ``received_inputs``,
    ``all_providers``, and ``provider_index`` parameters.  Access only the
    fields you need; unused ones require no ``noqa`` comment.

    Attributes:
        own_context: The context object produced by ``create_context()`` before
            any inputs are merged.
        received_inputs: Payloads delivered by other providers whose input
            schema matched this provider's ``get_inputs_schema()``.
        all_providers: Snapshot of every provider the loader knows about.
        provider_index: Position of this provider in the load order.
    """

    own_context: ContextT
    received_inputs: list[InputT]
    all_providers: list[ProviderEntry]
    provider_index: int


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

    # Optional mode-scoped handler classes.  When set, ``call_provider_method``
    # routes to the correct handler instead of calling the hook on the provider
    # directly.  If no handler is registered for the current mode, the
    # provider's own method (override or base no-op) is called.
    root_mode: type[ModeHandler[ContextT, InputT]] | None = None
    member_mode: type[ModeHandler[ContextT, InputT]] | None = None
    standalone_mode: type[ModeHandler[ContextT, InputT]] | None = None

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
        ctx_cls, _ = _get_provider_generic_args(self.__class__)
        if ctx_cls is None or not isinstance(ctx_cls, type) or not issubclass(ctx_cls, BaseContext):
            logger.warning(
                'provider_context_inference_failed',
                provider=self.__class__.__name__,
            )
            return BaseContext()  # type: ignore

        try:
            return ctx_cls()  # type: ignore
        except Exception as exc:  # noqa: BLE001 - we log and continue
            logger.warning(
                'provider_context_instantiation_failed',
                provider=self.__class__.__name__,
                error=str(exc),
            )
            return BaseContext()  # type: ignore

    def provide_inputs(
        self,
        opt: ProvideInputsOptions[ContextT],  # noqa: ARG002 - parameter may be unused
    ) -> list[InputT]:
        """Return payload objects that should be sent to other providers.

        The loader calls this hook when it needs outbound data from a
        provider. The implementation should return a sequence of
        :class:`BaseInputs` instances; returning raw mappings is only supported
        for legacy module-style providers and will be removed in v1.  The
        orchestration layer routes each item based on the receiving
        provider's input schema (provided via :meth:`get_inputs_schema`).
        Subclasses should override this method to supply whatever
        information is relevant to downstream providers.

        ``opt.all_providers`` is a list of :class:`ProviderEntry` instances;
        only the ``input_type``/``alias`` attributes are useful for most
        providers.  Access ``opt.own_context`` for this provider's current
        context, and ``opt.provider_index`` for the load-order position.

        The default returns an empty list.
        """
        return []

    def finalize_context(
        self,
        opt: FinalizeContextOptions[ContextT, InputT],
    ) -> ContextT:
        """Optionally apply inputs received from other providers.

        ``opt.own_context`` is the context object produced by
        ``create_context()`` before any inputs are merged.
        ``opt.received_inputs`` is a list of payloads delivered by other
        providers whose ``get_inputs_schema()`` matched the values.
        ``opt.all_providers`` is a snapshot of every provider the loader
        knows about; inspect ``alias`` or ``input_type`` on each entry as
        needed.  ``opt.provider_index`` is the position of this provider in
        the load order.

        Default: return the unmodified ``opt.own_context``.
        """
        return opt.own_context

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

        SessionBundle that need a nonstandard schema or that return values of
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

        Default: empty mapping.
        """
        return {}

    def create_anchors(
        self,
        context: ContextT,  # noqa: ARG002 - parameter may be unused
    ) -> dict[str, str]:
        """Optional: return anchors mapping for this provider.

        Default: no anchors (empty dict).
        """
        return {}

    def create_default_symlinks(
        self,
        context: ContextT,  # noqa: ARG002 - parameter may be unused
    ) -> list[Symlink]:
        """Optional: return the default symlinks this provider wants created.

        The merged provider context (a 'ContextT' instance) is passed so
        implementations can inspect it — for example to skip symlinks in
        ``member`` mode.  The context follows the same convention as
        :meth:`create_file_mappings` and is routed through
        :func:`call_provider_method` so that mode handlers (see
        :class:`ModeHandler`) receive it correctly.

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


def call_provider_method(
    inst: Provider[ContextT, InputT],
    method_name: str,
    arg: ContextT | ProvideInputsOptions[ContextT] | FinalizeContextOptions[ContextT, Any],
    /,
) -> object:
    """Call a provider hook, routing to the mode handler if one is registered.

    Orchestration callers use this instead of calling the hook directly so
    that :class:`Provider` itself has no knowledge of mode dispatch.

    ``arg`` is passed through to the target method unchanged — it is either a
    plain context (for single-context hooks such as ``create_anchors``) or an
    options object (:class:`ProvideInputsOptions` /
    :class:`FinalizeContextOptions`) for hooks that need extra data.

    Resolution order:

    1. The mode is read from the context's ``repolish.workspace.mode`` field.
       For options objects the context is taken from ``arg.own_context``.  If
       no ``repolish`` attribute exists the mode defaults to ``'standalone'``.
    2. If a handler class is registered on ``inst`` for the current mode a
       cached instance is used and the method is called on it.
    3. Otherwise the provider's own implementation is called — whether that is
       an explicit override in the subclass or the base-class no-op.

    Handler instances are lazily created and cached on the provider instance
    under ``_mode_handler_instances`` so repeated calls share the same object.
    """
    ctx_for_mode: object = arg.own_context if isinstance(arg, (ProvideInputsOptions, FinalizeContextOptions)) else arg
    repolish_ctx = getattr(ctx_for_mode, 'repolish', None)
    workspace_ctx = getattr(repolish_ctx, 'workspace', None)
    mode: str = getattr(workspace_ctx, 'mode', None) or 'standalone'

    handler_cls: type[ModeHandler[ContextT, InputT]] | None = None
    if mode == 'root':
        handler_cls = inst.root_mode
    elif mode == 'member':
        handler_cls = inst.member_mode
    else:
        handler_cls = inst.standalone_mode

    if handler_cls is not None:
        cache: dict[str, ModeHandler[ContextT, InputT]] = vars(inst).setdefault(
            '_mode_handler_instances',
            {},
        )
        if mode not in cache:
            handler = handler_cls()
            # Copy all ModeHandler-declared data attributes from the provider.
            # Most attributes are copied verbatim; templates_root is the only
            # mode-dependent exception (scoped to provider_root/{mode}/).
            # If ModeHandler gains another attribute that needs mode-specific
            # derivation, add a special case for it below.
            for attr in ModeHandler.__annotations__:
                value = getattr(inst, attr, getattr(handler, attr))
                if attr == 'templates_root':
                    value = inst.templates_root / mode
                setattr(handler, attr, value)
            cache[mode] = handler
        _target: ModeHandler[ContextT, InputT] | Provider[ContextT, InputT] = cache[mode]
    else:
        _target = inst

    return getattr(_target, method_name)(arg)


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
# that code doing `from repolish.providers.models.provider import FileMode`
# continues to work.  The canonical location is repolish.providers.models.files.
__all__ = [
    'ContextT',
    'FileMode',
    'FinalizeContextOptions',
    'InputT',
    'ModeHandler',
    'ProvideInputsOptions',
    'Provider',
    'ProviderEntry',
    'T',
    '_get_provider_generic_args',
    'call_provider_method',
    'get_provider_context',
    'get_provider_inputs',
    'get_provider_inputs_schema',
]
