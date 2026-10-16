from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel as _BaseModel

from repolish.providers._log import logger

if TYPE_CHECKING:
    from collections.abc import Sequence
from repolish.providers.models import (
    BaseContext,
    BaseInputs,
    FacetFinalizeOptions,
    FinalizeContextOptions,
    GlobalContext,
    ProviderEntry,
    ProviderFacet,
    ProviderInfo,
    call_provider_method,
    get_global_context,
    instantiate_facets,
)
from repolish.providers.models import (
    Provider as _ProviderBase,
)
from repolish.providers.models.context import RepolishContext


def _validate_raw_inputs(
    raw_inputs: list[BaseInputs],
    inputs_schema: type[BaseInputs] | None,
) -> list[BaseInputs]:
    """Validate a sequence of inputs against a pydantic schema if provided."""
    if inputs_schema is None:
        return raw_inputs

    validated: list[BaseInputs] = []
    for v in raw_inputs:
        if isinstance(v, BaseInputs):
            if isinstance(v, inputs_schema):
                validated.append(v)
            else:
                validated.append(inputs_schema.model_validate(v.model_dump()))
        else:
            validated.append(inputs_schema.model_validate(v))
    return validated


def _prepare_own_model(
    provider_contexts: dict[str, BaseContext],
    provider_id: str,
    global_context: GlobalContext | None = None,
) -> BaseContext:
    """Return the context object to pass to `finalize_context`.

    Uses the already-collected (and override-applied) context from
    `provider_contexts` so that `finalize_context` always sees the patched
    values.  Injects the global repolish namespace when present.
    """
    own_model = provider_contexts.get(provider_id, BaseContext())

    if isinstance(own_model, _BaseModel) and hasattr(own_model, 'repolish'):
        resolved_ctx = global_context if global_context is not None else get_global_context()
        # Build a RepolishContext preserving the provider identity already on
        # the context so that {{ repolish.provider.alias }} etc. remain valid
        # after this re-injection of the global namespace.
        existing_provider = getattr(
            own_model.repolish,
            'provider',
            ProviderInfo(),
        )
        repolish_ctx = RepolishContext(
            repo=resolved_ctx.repo,
            year=resolved_ctx.year,
            workspace=resolved_ctx.workspace,
            provider=existing_provider,
        )
        own_model = own_model.model_copy(
            update={'repolish': repolish_ctx},
        )

    return own_model


def _invoke_finalize(  # noqa: PLR0913 - we'll get this refactor for v1
    inst: _ProviderBase,
    own_model: BaseContext,
    validated_inputs: list[BaseInputs],
    all_providers_list: list[ProviderEntry],
    idx: int,
    provider_id: str,
) -> BaseContext:
    """Call `finalize_context` with consistent logging on failure."""
    try:
        return cast(
            'BaseContext',
            call_provider_method(
                inst,
                'finalize_context',
                FinalizeContextOptions(
                    own_context=own_model,
                    received_inputs=validated_inputs,
                    all_providers=all_providers_list,
                    provider_index=idx,
                ),
            ),
        )
    except Exception:
        logger.exception(
            'finalize_context_failed',
            provider=provider_id,
            index=idx,
        )
        raise


def _claiming_facet(
    facet_schemas: Sequence[tuple[ProviderFacet, type[BaseInputs]]],
    inp: BaseInputs,
) -> ProviderFacet | None:
    """Return the first facet whose schema exactly matches *inp*."""
    for facet, schema in facet_schemas:
        if isinstance(inp, schema):
            return facet
    return None


def _partition_facet_inputs(
    facets: Sequence[ProviderFacet],
    own_schema: type[BaseInputs] | None,
    raw_inputs: list[BaseInputs],
) -> tuple[list[BaseInputs], dict[str, list[BaseInputs]]]:
    """Split raw inputs into the provider's share and each facet's share.

    A payload that exactly matches the provider's own schema goes to the
    provider. Otherwise the first facet whose schema exactly matches claims
    it. Anything else remains with the provider, preserving the pre-facet
    behavior for payloads delivered through the structural fallback.
    """
    facet_schemas = [(facet, schema) for facet in facets if (schema := facet.get_inputs_schema()) is not None]
    if not facet_schemas:
        return list(raw_inputs), {}

    own_inputs: list[BaseInputs] = []
    by_facet: dict[str, list[BaseInputs]] = {}
    for inp in raw_inputs:
        if own_schema is not None and isinstance(inp, own_schema):
            own_inputs.append(inp)
            continue
        facet = _claiming_facet(facet_schemas, inp)
        if facet is None:
            own_inputs.append(inp)
        else:
            by_facet.setdefault(facet.name, []).append(inp)
    return own_inputs, by_facet


def _finalize_facet_contexts(  # noqa: PLR0913
    facets: Sequence[ProviderFacet],
    provider_id: str,
    own_ctx: BaseContext,
    by_facet: dict[str, list[BaseInputs]],
    all_providers_list: list[ProviderEntry],
    idx: int,
    global_context: GlobalContext | None,
) -> None:
    """Run each facet's ``finalize_context`` and store the result.

    Writes into ``own_ctx.facets``, which is the provider context's live
    map, so results are visible to later phases (spec collection, template
    rendering). A facet whose ``finalize_context`` raises keeps its
    pre-finalize context; one broken facet must not stop the run, matching
    how facet context creation is treated.
    """
    for facet in facets:
        fctx = own_ctx.facets.get(facet.name)
        if fctx is None:
            continue
        fctx = _prepare_facet_model(fctx, global_context)
        try:
            new_fctx = facet.finalize_context(
                FacetFinalizeOptions(
                    own_context=fctx,
                    received_inputs=by_facet.get(facet.name, []),
                    all_providers=all_providers_list,
                    provider_index=idx,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - one broken facet must not stop the run
            logger.warning(
                'facet_finalize_context_raised',
                provider=provider_id,
                facet=facet.name,
                error=str(exc),
            )
            continue
        if isinstance(new_fctx, BaseContext):
            own_ctx.facets[facet.name] = new_fctx


def _prepare_facet_model(
    fctx: BaseContext,
    global_context: GlobalContext | None,
) -> BaseContext:
    """Return *fctx* with a fresh ``repolish`` namespace injected.

    Same contract as :func:`_prepare_own_model` but for a facet context
    passed directly instead of looked up by provider id.
    """
    if not isinstance(fctx, _BaseModel) or not hasattr(fctx, 'repolish'):
        return fctx
    resolved_ctx = global_context if global_context is not None else get_global_context()
    existing_provider = getattr(fctx.repolish, 'provider', ProviderInfo())
    repolish_ctx = RepolishContext(
        repo=resolved_ctx.repo,
        year=resolved_ctx.year,
        workspace=resolved_ctx.workspace,
        provider=existing_provider,
    )
    return fctx.model_copy(update={'repolish': repolish_ctx})


def finalize_provider_contexts(  # noqa: PLR0913
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    received_inputs: dict[str, list[BaseInputs]],
    provider_contexts: dict[str, BaseContext],
    all_providers_list: list[ProviderEntry],
    global_context: GlobalContext | None = None,
) -> None:
    """Mutate `provider_contexts` by running finalize_context on each instance."""
    for idx, (provider_id, _module_dict) in enumerate(module_cache):
        inst = instances[idx]
        if not inst:
            continue

        raw_inputs = received_inputs.get(provider_id, [])
        inputs_schema = inst.get_inputs_schema()
        facets = instantiate_facets(inst)
        own_inputs, by_facet = _partition_facet_inputs(
            facets,
            inputs_schema,
            raw_inputs,
        )
        validated_inputs = _validate_raw_inputs(own_inputs, inputs_schema)

        own_model = _prepare_own_model(
            provider_contexts,
            provider_id,
            global_context,
        )

        new_ctx = _invoke_finalize(
            inst,
            own_model,
            validated_inputs,
            all_providers_list,
            idx,
            provider_id,
        )
        provider_contexts[provider_id] = new_ctx

        if isinstance(new_ctx, BaseContext):
            _finalize_facet_contexts(
                facets,
                provider_id,
                new_ctx,
                by_facet,
                all_providers_list,
                idx,
                global_context,
            )
