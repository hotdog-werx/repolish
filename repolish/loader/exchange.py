from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel as _BaseModel
from pydantic_core import ValidationError

from repolish.loader._log import logger
from repolish.loader.models import (
    BaseContext,
    BaseInputs,
    GlobalContext,
    ProviderEntry,
    get_global_context,
)
from repolish.loader.models import Provider as _ProviderBase


def build_provider_metadata(
    module_cache: list[tuple[str, dict]],
) -> list[_ProviderBase | None]:
    """Return the provider instance list from the module cache.

    Each module is expected to expose its provider via the
    ``_repolish_provider_instance`` key.  Entries without an instance
    (or with a non-Provider object) produce a ``None`` slot so that
    index-based pairing with ``module_cache`` is preserved.
    """
    instances: list[_ProviderBase | None] = []

    for _idx, (_provider_id, module_dict) in enumerate(module_cache):
        inst = module_dict.get('_repolish_provider_instance')
        instances.append(inst if isinstance(inst, _ProviderBase) else None)

    return instances


def _retrieve_instance_inputs(
    provider_id: str,
    idx: int,
    inst: _ProviderBase,
    # context values are arbitrary; using ``Any`` prevents invariant-type
    # complaints when callers hold more specific mappings.
    provider_contexts: dict[str, Any],
    all_providers_list: list[ProviderEntry],
) -> list[object] | None:
    """Call an instance's `provide_inputs`.

    Uses the previously collected context object which already includes any
    configuration overrides, so `provide_inputs` sees the patched values.
    """
    own_model = provider_contexts.get(provider_id, {})
    try:
        raw = inst.provide_inputs(
            own_model,
            all_providers_list,
            idx,
        )
    except Exception:
        logger.exception(
            'provider_inputs_failed',
            provider=provider_id,
            provider_index=idx,
        )
        raise
    return cast('list[object]', raw)


def _schema_matches(schema: type[_BaseModel], value: object) -> bool:
    """Return True if `value` satisfies `schema`.

    Checks exact type first for performance, then falls back to
    `model_validate` to handle structurally compatible models loaded from
    separate dynamic modules (which produce distinct class objects).
    """
    if isinstance(value, schema):
        return True
    try:
        data = value.model_dump() if isinstance(value, _BaseModel) else value
        schema.model_validate(data)
    except ValidationError:
        return False
    return True


def _distribute_payloads(
    inputs_list: list[object],
    state: _GatherState,
) -> None:
    """Route a provider's outputs to every other provider.

    Every payload is delivered to all providers regardless of position;
    schema filtering ensures unrelated providers are not burdened with
    irrelevant objects.
    """
    for inp in inputs_list:
        for entry in state.all_providers_list:
            schema = entry.input_type
            if not schema:
                continue
            if _schema_matches(schema, inp):
                state.received_inputs.setdefault(entry.provider_id, []).append(
                    cast('BaseInputs', inp),
                )


@dataclass
class _GatherState:
    provider_contexts: dict[str, BaseContext]
    all_providers_list: list[ProviderEntry]
    received_inputs: dict[str, list[BaseInputs]]


def _collect_for_provider(
    idx: int,
    provider_id: str,
    inst: _ProviderBase | None,
    state: _GatherState,
) -> None:
    """Process a single provider entry and update `state.received_inputs`."""
    inputs = (
        _retrieve_instance_inputs(
            provider_id,
            idx,
            inst,
            state.provider_contexts,
            state.all_providers_list,
        )
        if inst
        else []
    )

    if inputs:
        _distribute_payloads(inputs, state)


def gather_received_inputs(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, BaseContext],
    all_providers_list: list[ProviderEntry],
) -> dict[str, list[BaseInputs]]:
    """Collect provider inputs and organize them by recipient provider id."""
    state = _GatherState(
        provider_contexts=provider_contexts,
        all_providers_list=all_providers_list,
        received_inputs={},
    )

    for idx, (provider_id, _) in enumerate(module_cache):
        _collect_for_provider(
            idx,
            provider_id,
            instances[idx],
            state,
        )

    return state.received_inputs


# helpers used by finalize_provider_contexts --------------------------------


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
) -> BaseContext:
    """Return the context object to pass to `finalize_context`.

    Uses the already-collected (and override-applied) context from
    `provider_contexts` so that `finalize_context` always sees the patched
    values.  Injects the global repolish namespace when present.
    """
    own_model = provider_contexts.get(provider_id, BaseContext())

    if isinstance(own_model, _BaseModel) and hasattr(own_model, 'repolish'):
        glob = get_global_context().model_dump()
        if glob:
            own_model = own_model.model_copy(
                update={'repolish': GlobalContext(**glob)},
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
        return inst.finalize_context(
            own_model,
            validated_inputs,
            all_providers_list,
            idx,
        )
    except Exception:
        logger.exception(
            'finalize_context_failed',
            provider=provider_id,
            index=idx,
        )
        raise


def finalize_provider_contexts(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    received_inputs: dict[str, list[BaseInputs]],
    provider_contexts: dict[str, BaseContext],
    all_providers_list: list[ProviderEntry],
) -> None:
    """Mutate `provider_contexts` by running finalize_context on each instance."""
    for idx, (provider_id, _module_dict) in enumerate(module_cache):
        inst = instances[idx]
        if not inst:
            continue

        raw_inputs = received_inputs.get(provider_id, [])
        inputs_schema = inst.get_inputs_schema()
        validated_inputs = _validate_raw_inputs(raw_inputs, inputs_schema)

        own_model = _prepare_own_model(provider_contexts, provider_id)

        new_ctx = _invoke_finalize(
            inst,
            own_model,
            validated_inputs,
            all_providers_list,
            idx,
            provider_id,
        )
        provider_contexts[provider_id] = new_ctx
