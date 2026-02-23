from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel as _BaseModel
from pydantic_core import ValidationError

from repolish.loader._log import logger
from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.models import ProviderEntry
from repolish.loader.module_loader import ModuleProviderAdapter


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
        inst = module_dict.get('_repolish_provider_instance')
        # explicit flag may be any truthy value; adapters should not count as
        # migrated even though they are instances of ``Provider``.  only real
        # class-based providers cause automatic migration.
        is_adapter = isinstance(inst, ModuleProviderAdapter)
        migrated = bool(module_dict.get('provider_migrated')) or (inst is not None and not is_adapter)
        provider_migrated_map[provider_id] = migrated

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
    try:
        try:
            own_model = inst.create_context()
        except Exception:  # noqa: BLE001
            own_model = provider_contexts.get(provider_id, {})
        # the new public API
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
    """Route anonymous payloads to matching recipients.

    `inputs_list` is the sequence produced by a provider's
    `provide_inputs()`.  For each element we attempt to validate
    it against every provider's declared `get_inputs_schema()`; successes
    result in the value being appended to that provider's incoming list.  A
    single payload may match multiple schemas.  Order is preserved so earlier
    senders have priority in consumption.
    """
    recipients = [(pid, schema) for pid, _ctx, schema in state.all_providers_list if schema]
    pairs = [(pid, inp) for inp in inputs_list for pid, schema in recipients if _schema_matches(schema, inp)]
    for pid, inp in pairs:
        state.received_inputs.setdefault(pid, []).append(inp)


@dataclass
class _GatherState:
    provider_contexts: dict[str, object]
    all_providers_list: list[ProviderEntry]
    canonical_name_to_pid: dict[str, str]
    has_recipient_after: list[bool]
    received_inputs: dict[str, list[object]]


def _collect_for_provider(
    idx: int,
    provider_id: str,
    inst: _ProviderBase | None,
    state: _GatherState,
) -> None:
    """Process a single provider entry and update ``state.received_inputs``.

    The heavy lifting of input extraction is delegated to helpers so this
    function remains simple and takes just five arguments.
    """
    if not state.has_recipient_after[idx]:
        return

    if not inst:
        logger.warning(
            'module_provide_inputs_not_supported',
            provider=provider_id,
        )
        return

    inputs = _retrieve_instance_inputs(
        provider_id,
        idx,
        inst,
        state.provider_contexts,
        state.all_providers_list,
    )

    if inputs:
        # only list form is supported now; we dispatch directly
        _distribute_payloads(inputs, state)


def gather_received_inputs(  # noqa: PLR0913 -- helper function for a complex step
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, object],
    all_providers_list: list[ProviderEntry],
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
    all_providers_list: list[tuple[str, dict[str, object], type[_BaseModel] | None]],
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
