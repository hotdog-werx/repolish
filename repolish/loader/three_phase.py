from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel as _BaseModel

from repolish.loader._log import logger
from repolish.loader.models import Provider as _ProviderBase

# helpers previously nested inside orchestrator._run_three_phase ------------


def build_provider_metadata(
    module_cache: list[tuple[str, dict]],
) -> tuple[dict[str, bool], list[_ProviderBase | None], dict[str, str]]:
    """Compute migration flags, provider instances, and canonical names.

    Returns a tuple: (migrated_map, instances, canonical_name_to_pid).
    """
    provider_migrated_map: dict[str, bool] = {}
    instances: list[_ProviderBase | None] = []
    canonical_name_to_pid: dict[str, str] = {}

    for _idx, (provider_id, module_dict) in enumerate(module_cache):
        migrated = module_dict.get('provider_migrated')
        provider_migrated_map[provider_id] = bool(migrated) if isinstance(migrated, bool) else False

        inst = module_dict.get('_repolish_provider_instance')
        instances.append(inst if isinstance(inst, _ProviderBase) else None)
        if inst:
            try:
                name = inst.get_provider_name()
            except Exception:  # noqa: BLE001 -- provider code should not be able to break loading
                name = None
            if isinstance(name, str) and name:
                canonical_name_to_pid[name] = provider_id

    return provider_migrated_map, instances, canonical_name_to_pid


def compute_recipient_flags(
    instances: list[_ProviderBase | None],
) -> list[bool]:
    """Return boolean list marks which providers have recipients after them."""
    n = len(instances)
    has_recipient_after = [False] * n
    found_recipient = False
    for i in range(n - 1, -1, -1):
        has_recipient_after[i] = found_recipient
        inst = instances[i]
        if inst and inst.get_inputs_schema() is not None:
            found_recipient = True
    return has_recipient_after


# helpers used by gather_received_inputs ----------------------------------


def _normalize_inputs(
    provider_id: str,
    raw: object | None,
) -> dict[str, object] | None:
    """Validate and cast a provider-generated value to a dict, logging on error."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning(
            'collect_provider_inputs_must_return_dict',
            provider=provider_id,
        )
        return None
    return cast('dict[str, object]', raw)


def ctx_to_dict(ctx: object | None) -> dict[str, object]:
    """Return a plain dict representation for a provider context object.

    The context value may be a ``BaseModel`` (in which case we call
    ``model_dump()``) or already a dict.  ``None`` becomes an empty dict.
    """
    if isinstance(ctx, _BaseModel):
        return ctx.model_dump()
    return cast('dict[str, object]', ctx or {})


def _retrieve_instance_inputs(
    provider_id: str,
    idx: int,
    inst: _ProviderBase,
    provider_contexts: dict[str, object],
    all_providers_list: list[tuple[str, dict[str, object]]],
) -> dict[str, object] | None:
    """Call an instance's ``collect_provider_inputs`` and normalise output."""
    try:
        try:
            own_model = inst.create_context()
        except Exception:  # noqa: BLE001
            own_model = provider_contexts.get(provider_id, {})
        raw = inst.collect_provider_inputs(
            own_model,
            all_providers_list,
            idx,
        )
    except Exception:
        logger.exception(
            'collect_provider_inputs_failed',
            provider=provider_id,
            index=idx,
        )
        raise
    return _normalize_inputs(provider_id, raw)


def _retrieve_module_inputs(
    provider_id: str,
    idx: int,
    module_dict: dict,
    provider_contexts: dict[str, object],
    all_providers_list: list[tuple[str, dict[str, object]]],
) -> dict[str, object] | None:
    """Invoke a module-level ``collect_provider_inputs`` if present."""
    module_collect = module_dict.get('collect_provider_inputs')
    if not callable(module_collect):
        return None
    try:
        raw = module_collect(
            ctx_to_dict(provider_contexts.get(provider_id)),
            all_providers_list,
            idx,
        )
    except Exception:
        logger.exception(
            'collect_provider_inputs_failed',
            provider=provider_id,
            index=idx,
        )
        raise
    return _normalize_inputs(provider_id, raw)


def _resolve_target_pid(
    recipient_key: str,
    canonical_name_to_pid: dict[str, str],
    provider_contexts: dict[str, object],
) -> str | None:
    """Translate a recipient key into a provider id, if possible."""
    return canonical_name_to_pid.get(recipient_key) or (recipient_key if recipient_key in provider_contexts else None)


def _process_inputs_map(
    provider_id: str,
    inputs_map: dict[str, object],
    received_inputs: dict[str, list[object]],
    canonical_name_to_pid: dict[str, str],
    provider_contexts: dict[str, object],
) -> None:
    """Add validated entries from ``inputs_map`` into ``received_inputs``."""
    for recipient_key, inp in inputs_map.items():
        target_pid = _resolve_target_pid(
            recipient_key,
            canonical_name_to_pid,
            provider_contexts,
        )
        if not target_pid:
            logger.warning(
                'collect_provider_inputs_unresolved_recipient',
                sender=provider_id,
                recipient=recipient_key,
            )
            continue
        received_inputs.setdefault(target_pid, []).append(inp)


@dataclass
class _GatherState:
    provider_contexts: dict[str, object]
    all_providers_list: list[tuple[str, dict[str, object]]]
    canonical_name_to_pid: dict[str, str]
    has_recipient_after: list[bool]
    received_inputs: dict[str, list[object]]


def _collect_for_provider(
    idx: int,
    provider_id: str,
    module_dict: dict,
    inst: _ProviderBase | None,
    state: _GatherState,
) -> None:
    """Process a single provider entry and update ``state.received_inputs``.

    The heavy lifting of input extraction is delegated to helpers so this
    function remains simple and takes just five arguments.
    """
    if not state.has_recipient_after[idx]:
        return

    if inst:
        inputs_map = _retrieve_instance_inputs(
            provider_id,
            idx,
            inst,
            state.provider_contexts,
            state.all_providers_list,
        )
    else:
        inputs_map = _retrieve_module_inputs(
            provider_id,
            idx,
            module_dict,
            state.provider_contexts,
            state.all_providers_list,
        )

    if inputs_map:
        _process_inputs_map(
            provider_id,
            inputs_map,
            state.received_inputs,
            state.canonical_name_to_pid,
            state.provider_contexts,
        )


def gather_received_inputs(  # noqa: PLR0913 -- helper function for a complex step
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, object],
    all_providers_list: list[tuple[str, dict[str, object]]],
    canonical_name_to_pid: dict[str, str],
    has_recipient_after: list[bool],
) -> dict[str, list[object]]:
    """Collect provider inputs and organize them by recipient provider id."""
    state = _GatherState(
        provider_contexts=provider_contexts,
        all_providers_list=all_providers_list,
        canonical_name_to_pid=canonical_name_to_pid,
        has_recipient_after=has_recipient_after,
        received_inputs={},
    )

    for idx, (provider_id, module_dict) in enumerate(module_cache):
        _collect_for_provider(
            idx,
            provider_id,
            module_dict,
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
            # ``isinstance(v, dict)`` branch was originally more explicit but
            # did not change the outcome. keeping a single catch-all makes the
            # logic easier to follow and removes a redundant check.
            validated.append(inputs_schema.model_validate(v))
    return validated


def _get_own_model(
    inst: _ProviderBase,
    provider_contexts: dict[str, object],
    provider_id: str,
) -> object:
    """Return the provider's context model, falling back to existing context on error."""
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
    ``BaseModel`` or a ``dict``).  The orchestrator will convert to a dict when
    building the merged context; retaining the original object allows us to
    pass a typed ``ContextT`` instance to helpers such as
    ``create_file_mappings()``.
    """
    if isinstance(new_ctx, _BaseModel | dict):
        provider_contexts[provider_id] = new_ctx
        return
    msg = 'finalize_context() must return a dict or Pydantic model'
    raise TypeError(msg)


def finalize_provider_contexts(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    received_inputs: dict[str, list[object]],
    provider_contexts: dict[str, object],
    all_providers_list: list[tuple[str, dict[str, object]]],
) -> None:
    """Mutate ``provider_contexts`` by running finalize_context on each instance.

    This handles schema validation and model/dict conversion.
    """
    for idx, (provider_id, _module_dict) in enumerate(module_cache):
        inst = instances[idx]
        if not inst:
            continue

        raw_inputs = received_inputs.get(provider_id, [])
        if not raw_inputs:
            continue

        inputs_schema = inst.get_inputs_schema()
        validated_inputs = _validate_raw_inputs(raw_inputs, inputs_schema)

        own_model = _get_own_model(inst, provider_contexts, provider_id)

        try:
            new_ctx = inst.finalize_context(
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

        _store_new_context(provider_contexts, provider_id, new_ctx)
