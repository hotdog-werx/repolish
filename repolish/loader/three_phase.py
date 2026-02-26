from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel as _BaseModel
from pydantic_core import ValidationError

from repolish.loader._log import logger
from repolish.loader.models import (
    GlobalContext,
    ProviderEntry,
    get_global_context,
)
from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.module_loader import ModuleProviderAdapter


def build_provider_metadata(
    module_cache: list[tuple[str, dict]],
) -> tuple[dict[str, bool], list[_ProviderBase | None]]:
    """Compute migration flags and provider instances.

    Historically this helper also returned a `canonical_name_to_pid` map
    used for explicit name-based routing.  that mechanism has been removed,
    so the helper now returns only the two values still needed by the loader.
    The map is no longer constructed at all.
    """
    provider_migrated_map: dict[str, bool] = {}
    instances: list[_ProviderBase | None] = []

    for _idx, (provider_id, module_dict) in enumerate(module_cache):
        inst = module_dict.get('_repolish_provider_instance')
        # explicit flag may be any truthy value; adapters should not count as
        # migrated even though they are instances of `Provider`.  only real
        # class-based providers cause automatic migration.
        is_adapter = isinstance(inst, ModuleProviderAdapter)
        migrated = bool(module_dict.get('provider_migrated')) or (inst is not None and not is_adapter)
        provider_migrated_map[provider_id] = migrated

        instances.append(inst if isinstance(inst, _ProviderBase) else None)

    return provider_migrated_map, instances


def compute_recipient_flags(
    instances: list[_ProviderBase | None],
) -> list[bool]:
    """Return boolean list marking which providers declare an input schema.

    Historically the loader used this to avoid calling `provide_inputs` on
    senders if no later provider declared a schema.  That optimisation proved
    confusing and has been deprecated; the orchestration no longer relies on
    these flags.  The helper is retained for backwards compatibility and
    performance analysis but the returned list is ignored by newer code.
    """
    n = len(instances)
    has_schema = [False] * n
    for i, inst in enumerate(instances):
        if inst and inst.get_inputs_schema() is not None:
            has_schema[i] = True
    return has_schema


def _retrieve_instance_inputs(
    provider_id: str,
    idx: int,
    inst: _ProviderBase,
    provider_contexts: dict[str, object],
    all_providers_list: list[ProviderEntry],
) -> list[object] | None:
    """Call an instance's `provide_inputs` (or deprecated `collect_*`).

    We still support the old method name when defined; providers using it
    receive a warning from the class shim above, so the loader itself doesn't
    need to duplicate that logic.
    """
    # prefer the previously collected context object which already
    # includes any configuration overrides.  creating a fresh context here
    # would bypass those overrides and lead to stale values during the
    # `provide_inputs` call.
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
    if isinstance(value, _BaseModel):
        return isinstance(value, schema)
    try:
        schema.model_validate(value)
    except ValidationError:
        return False
    else:
        return True


def _distribute_payloads(
    inputs_list: list[object],
    state: _GatherState,
) -> None:
    """Route a provider's outputs to every other provider.

    Earlier iterations only delivered payloads to providers appearing after
    the sender in the load order.  That optimisation confused users and
    prevented even correctly-typed providers from seeing inputs simply because
    they were listed earlier.  The loader now distributes every payload to all
    providers regardless of position; it is the recipient's responsibility to
    inspect and consume what it cares about.
    """
    # iterate over the entire provider list rather than slicing.  we still
    # respect schema filtering so unrelated providers are not burdened with
    # irrelevant objects, but there is no longer any directional constraint.
    for inp in inputs_list:
        for entry in state.all_providers_list:
            schema = entry.input_type
            if not schema:
                continue
            if _schema_matches(schema, inp):
                state.received_inputs.setdefault(entry.provider_id, []).append(
                    inp,
                )


@dataclass
class _GatherState:
    provider_contexts: dict[str, object]
    all_providers_list: list[ProviderEntry]
    has_recipient_after: list[bool]
    received_inputs: dict[str, list[object]]


def _collect_for_provider(
    idx: int,
    provider_id: str,
    inst: _ProviderBase | None,
    state: _GatherState,
) -> None:
    """Process a single provider entry and update `state.received_inputs`.

    We always call the provider's inputs hook (instance or module) regardless
    of what other providers declare; any returned payloads are then routed
    based on schemas. The prior optimisation that skipped senders when no
    later providers could receive them has been removed, but the *directional*
    nature of input flow (only to later providers) is preserved by the
    dispatcher.
    """
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
        # only list form is supported now; dispatch forward only
        _distribute_payloads(inputs, state)


def gather_received_inputs(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, object],
    all_providers_list: list[ProviderEntry],
    has_recipient_after: list[bool],
) -> dict[str, list[object]]:
    """Collect provider inputs and organize them by recipient provider id."""
    state = _GatherState(
        provider_contexts=provider_contexts,
        all_providers_list=all_providers_list,
        has_recipient_after=has_recipient_after,
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
    raw_inputs: list[object],
    inputs_schema: type[_BaseModel] | None,
) -> list[object]:
    """Validate a sequence of inputs against a pydantic schema if provided."""
    if inputs_schema is None:
        return raw_inputs

    validated: list[object] = []
    for v in raw_inputs:
        if isinstance(v, _BaseModel):
            if isinstance(v, inputs_schema):
                validated.append(v)
            else:
                validated.append(inputs_schema.model_validate(v.model_dump()))
        else:
            # dicts and any other payload type are handled identically; the
            # `isinstance(v, dict)` branch was originally more explicit but
            # did not change the outcome. keeping a single catch-all makes the
            # logic easier to follow and removes a redundant check.
            validated.append(inputs_schema.model_validate(v))
    return validated


def _get_own_model(
    inst: _ProviderBase,
    provider_contexts: dict[str, object],
    provider_id: str,
) -> object:
    """Return the provider's context model, falling back to existing context.

    This helper is no longer invoked during finalization; it remains for
    backwards-compatibility in case other callers need to recompute a model
    on the fly. The loader now prefers using the earlier-collected value from
    `provider_contexts` so we avoid duplicate `create_context` calls.
    """
    try:
        return inst.create_context()
    except Exception:  # noqa: BLE001
        return provider_contexts.get(provider_id, {})


def _store_new_context(
    provider_contexts: dict[str, object],
    provider_id: str,
    new_ctx: object,
) -> None:
    """Store a returned context value.

    Unlike earlier versions we keep the value exactly as returned (either a
    `BaseModel` or a `dict`).  The orchestrator will convert to a dict when
    building the merged context; retaining the original object allows us to
    pass a typed `ContextT` instance to helpers such as
    `create_file_mappings()`.
    """
    if isinstance(new_ctx, _BaseModel | dict):
        provider_contexts[provider_id] = new_ctx
        return
    msg = 'finalize_context() must return a dict or Pydantic model'
    raise TypeError(msg)


def _prepare_own_model(
    inst: _ProviderBase,
    provider_contexts: dict[str, object],
    provider_id: str,
) -> object:
    """Return the context object to pass to `finalize_context`.

    Encapsulates adapter handling, create_context fallback, and global
    namespace injection.
    """
    prev_ctx = provider_contexts.get(provider_id, {})
    if isinstance(inst, ModuleProviderAdapter):
        return prev_ctx

    try:
        own_model = inst.create_context()
    except Exception:  # noqa: BLE001
        own_model = prev_ctx

    if isinstance(own_model, _BaseModel) and hasattr(own_model, 'repolish'):
        glob = get_global_context().model_dump()
        if glob:
            if isinstance(glob, dict):
                glob = GlobalContext(**glob)
            own_model = own_model.model_copy(update={'repolish': glob})

    return own_model


def _invoke_finalize(  # noqa: PLR0913 - we'll get this refactor for v1
    inst: _ProviderBase,
    own_model: object,
    validated_inputs: list[object],
    all_providers_list: list[ProviderEntry],
    idx: int,
    provider_id: str,
) -> object:
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
    received_inputs: dict[str, list[object]],
    provider_contexts: dict[str, object],
    all_providers_list: list[ProviderEntry],
) -> None:
    """Mutate `provider_contexts` by running finalize_context on each instance.

    This handles schema validation and model/dict conversion.
    """
    for idx, (provider_id, _module_dict) in enumerate(module_cache):
        inst = instances[idx]
        if not inst:
            continue

        raw_inputs = received_inputs.get(provider_id, [])
        inputs_schema = inst.get_inputs_schema()
        validated_inputs = _validate_raw_inputs(raw_inputs, inputs_schema)

        own_model = _prepare_own_model(inst, provider_contexts, provider_id)

        new_ctx = _invoke_finalize(
            inst,
            own_model,
            validated_inputs,
            all_providers_list,
            idx,
            provider_id,
        )

        _store_new_context(provider_contexts, provider_id, new_ctx)
