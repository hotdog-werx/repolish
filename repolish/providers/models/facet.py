"""Provider facets: one class per managed file.

A facet breaks a provider's per-file work into a readable unit. Instead of
three mode classes each holding every file, one facet class holds one file
and all three modes: its context, its inputs, and its file's whole
contribution set live together, so adding a file means adding one small
class instead of touching the context model, the mode handlers, the
finalize logic, and the template wiring.

Facets are units of breakdown, not a replacement for the provider. The
provider still owns cross-file concerns: resource copies, symlinks, and
any behavior that is not about one specific managed file stay on the
provider (see ``docs/provider-development/facets.md`` for when and where
to use facets).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, Field

from repolish.providers._log import logger
from repolish.providers.models.context import BaseContext, BaseInputs

# Runtime imports on purpose: `FacetSpec` is a pydantic model, so its field
# annotations must resolve from module globals at class-creation time.
from repolish.providers.models.files import (  # noqa: TC001
    FileValidatorsByPath,
    InsertionRegistryByPath,
    TemplateMapping,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from repolish.providers.models.provider import ProviderEntry

# Same bounds as the provider type variables so type checkers enforce the
# context contract (BaseContext carries the ``repolish`` namespace facets
# branch on) and input contract (any Pydantic model) across facet classes.
FacetCtxT = TypeVar('FacetCtxT', bound=BaseContext)
FacetInpT = TypeVar('FacetInpT', bound=BaseModel)


class FacetSpec(BaseModel):
    """One facet's contributions, in the same shapes the regular hooks use.

    Returned by :meth:`ProviderFacet.create_spec`. Deliberately mirrors the
    :class:`~repolish.providers.models.FastLaneSpec` shapes minus
    ``file_copies`` and the lane-only fields: plain copies stay on the
    provider, because a facet owns exactly one file's work, not the
    provider's resource set.
    """

    file_mappings: dict[str, str | TemplateMapping] = Field(
        default_factory=dict,
    )
    """Destination path → source path or `TemplateMapping`, as in `create_file_mappings`."""
    file_insertions: InsertionRegistryByPath = Field(default_factory=dict)
    """Destination path → insertion-function name → callable, as in
    `create_file_insertions` (the explicit per-file map form)."""
    file_validators: FileValidatorsByPath = Field(default_factory=dict)
    """Destination path → validator name → validator callable or spec, as in
    `create_file_validators`."""


@dataclass
class FacetInputsOptions(Generic[FacetCtxT]):
    """Options bundle passed to :meth:`ProviderFacet.provide_inputs`.

    Attributes:
        own_context: This facet's context object.
        all_providers: Snapshot of every provider the loader knows about.
        provider_index: Position of the enclosing provider in the load order.
    """

    own_context: FacetCtxT
    all_providers: list[ProviderEntry]
    provider_index: int


@dataclass
class FacetFinalizeOptions(Generic[FacetCtxT, FacetInpT]):
    """Options bundle passed to :meth:`ProviderFacet.finalize_context`.

    Attributes:
        own_context: The facet's context as produced by ``create_context()``,
            after project overrides were applied.
        received_inputs: Only the payloads that matched this facet's schema.
            The framework does the split; the facet author never filters.
        all_providers: Snapshot of every provider the loader knows about.
        provider_index: Position of the enclosing provider in the load order.
    """

    own_context: FacetCtxT
    received_inputs: list[FacetInpT]
    all_providers: list[ProviderEntry]
    provider_index: int


@dataclass
class FacetSpecOptions(Generic[FacetCtxT]):
    """Options bundle passed to :meth:`ProviderFacet.create_spec`.

    Attributes:
        own_context: The facet's finalized context: the values
            ``finalize_context`` returned for this facet.
        provider_context: The enclosing provider's finalized context.
            Siblings are reachable through ``provider_context.facets``,
            so a facet can read what its siblings decided.
    """

    own_context: FacetCtxT
    provider_context: BaseContext


def _get_facet_generic_args(cls: type) -> tuple[type | None, type | None]:
    """Return (context_cls, input_cls) extracted from ``cls`` generics.

    Mirrors ``_get_provider_generic_args`` for facets: inspects
    ``__orig_bases__`` and returns the parameterized ``ProviderFacet`` type
    arguments when present, ``None`` otherwise.
    """
    from typing import get_args, get_origin  # noqa: PLC0415 - used only here

    bases = getattr(cls, '__orig_bases__', ())
    if not bases:  # pragma: no cover - unreachable defensively
        # Every ProviderFacet subclass inherits ``__orig_bases__`` through
        # the MRO (ProviderFacet itself defines the attribute), so a class
        # with none is never passed here.
        return None, None
    base = bases[0]
    if get_origin(base) is not ProviderFacet:
        return None, None
    args = get_args(base)
    ctx = args[0] if len(args) >= 1 else None
    inp = args[1] if len(args) >= 2 else None
    return ctx, inp


class ProviderFacet(ABC, Generic[FacetCtxT, FacetInpT]):
    """Base class for provider facets: one managed file's worth of provider.

    Declare facets with the explicit ordered ``facets`` class attribute on
    the enclosing :class:`~repolish.providers.models.Provider`::

        class WorkspaceProvider(Provider[WorkspaceContext, WorkspaceInputs]):
            facets = [GitignoreFacet, CiWorkflowsFacet]

    Each facet runs in every workspace mode and branches on
    ``ctx.repolish.workspace.mode`` itself when content must differ; there
    are no per-mode facet handlers. A mode that does not feed a facet
    simply sends no inputs (or the facet declares none).

    Facet contexts live on the provider context under ``facets`` (a name →
    context map), so siblings see each other through
    ``provider_context.facets`` and templates read them as
    ``{{ facets.<name>.<field> }}``. The facet's own file renders with the
    additional shorthand ``{{ facet.<field> }}``.

    Attributes:
        name: Registration key, e.g. ``'gitignore'``. Must be set by every
            subclass; two facets of one provider may not share a name.
        templates_root: The provider's templates directory, copied onto the
            facet when the framework instantiates it, so the same
            discovery patterns as provider hooks work here.
    """

    name: ClassVar[str]
    templates_root: Path = Path()

    def create_context(self) -> FacetCtxT:
        """Return this facet's initial context object.

        The default implementation mirrors
        :meth:`~repolish.providers.models.Provider.create_context`: it
        infers the context type from the generic arguments and
        instantiates it without parameters, falling back to a bare
        :class:`BaseContext` when inference or instantiation fails.
        Override to customize.
        """
        ctx_cls, _ = _get_facet_generic_args(self.__class__)
        if ctx_cls is None or not isinstance(ctx_cls, type) or not issubclass(ctx_cls, BaseContext):
            logger.warning(
                'facet_context_inference_failed',
                facet=self.__class__.__name__,
            )
            return cast('FacetCtxT', BaseContext())

        try:
            return cast('FacetCtxT', ctx_cls())
        except Exception as exc:  # noqa: BLE001 - we log and continue
            logger.warning(
                'facet_context_instantiation_failed',
                facet=self.__class__.__name__,
                error=str(exc),
            )
            return cast('FacetCtxT', BaseContext())

    def get_inputs_schema(self) -> type[FacetInpT] | None:
        """Return the Pydantic model class for this facet's *input* type.

        The framework routes a payload to the facet when it exactly
        isinstance-matches this schema (see
        :meth:`~repolish.providers.models.Provider.get_inputs_schema` for
        the provider-side contract). The default infers the class from the
        second generic argument; ``None`` means the facet receives nothing.
        """
        _, inp_cls = _get_facet_generic_args(self.__class__)
        if inp_cls is None:
            return None
        if isinstance(inp_cls, type) and issubclass(inp_cls, BaseInputs) and inp_cls is not BaseInputs:
            return cast('type[FacetInpT]', inp_cls)
        return None

    def provide_inputs(
        self,
        opt: FacetInputsOptions[FacetCtxT],  # noqa: ARG002 - parameter may be unused
    ) -> Sequence[BaseInputs]:
        """Return payload objects this facet wants to send to other providers.

        Same contract as :meth:`~repolish.providers.models.Provider.provide_inputs`.
        The default returns an empty list.
        """
        return []

    def finalize_context(
        self,
        opt: FacetFinalizeOptions[FacetCtxT, FacetInpT],
    ) -> FacetCtxT:
        """Apply the inputs routed to this facet and return the new context.

        ``opt.received_inputs`` holds only payloads whose schema exactly
        matched this facet's :meth:`get_inputs_schema`. Default: return the
        unmodified ``opt.own_context``.
        """
        return opt.own_context

    @abstractmethod
    def create_spec(self, opt: FacetSpecOptions[FacetCtxT]) -> FacetSpec:
        """Return this facet's contributions for its one managed file.

        Abstract on purpose: a facet exists to declare its file. The spec
        carries mappings, insertions, and validators in the same shapes the
        provider's regular hooks return; the framework merges them exactly
        as if the provider had declared them.
        """


def instantiate_facets(inst: object) -> list[ProviderFacet[Any, Any]]:
    """Return facet instances declared on a provider instance, in order.

    Reads the provider's explicit ``facets`` class attribute, instantiates
    each facet once per call, and copies the provider's ``templates_root``
    onto it (the same attribute ModeHandler receives). Providers without
    facets return an empty list.
    """
    facet_classes = getattr(inst, 'facets', None) or []
    instances: list[ProviderFacet[Any, Any]] = []
    for cls in facet_classes:
        facet = cls()
        facet.templates_root = getattr(inst, 'templates_root', Path())
        instances.append(facet)
    return instances


def facet_input_schemas(inst: object) -> list[type[BaseModel]]:
    """Return every declared facet's input schema, in facet order.

    Used by the pipeline to build ``ProviderEntry.input_types``; facets
    without an input schema contribute nothing.
    """
    schemas: list[type[BaseModel]] = []
    for facet in instantiate_facets(inst):
        schema = facet.get_inputs_schema()
        if schema is not None:
            schemas.append(schema)
    return schemas
