from __future__ import annotations

from typing import cast

from pydantic import BaseModel as _BaseModel

from repolish.providers._log import logger
from repolish.providers.models import (
    BaseContext,
    BaseInputs,
    FinalizeContextOptions,
    GlobalContext,
    ProviderEntry,
    ProviderInfo,
    call_provider_method,
    get_global_context,
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
        validated_inputs = _validate_raw_inputs(raw_inputs, inputs_schema)

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
