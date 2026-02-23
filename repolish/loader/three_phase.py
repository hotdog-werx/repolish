from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel as _BaseModel
from pydantic_core import ValidationError

from repolish.loader._log import logger
from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.models import ProviderEntry
from repolish.loader.module_loader import ModuleProviderAdapter
from repolish.misc import ctx_to_dict


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
    """Return boolean list marking which providers declare an input schema.

    Historically the loader used this to avoid calling ``provide_inputs`` on
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


# module-style providers still support a bare callable, but we no longer
# bother executing it.  Modules are legacy and will eventually vanish; in the
# meantime we treat them as having no outgoing inputs.  Returning ``[]`` keeps
# callers happy without needing to understand whatever the old module might
# have attempted to do.
def _retrieve_module_inputs(
    provider_id: str,
    idx: int,
    module_dict: dict,
    provider_contexts: dict[str, object],
    all_providers_list: list[ProviderEntry],
) -> list[object] | None:
    """Legacy wrapper for module-based providers.

    Historically this invoked a ``provide_inputs`` callable defined at the
    module level.  Those hooks have been deprecated for years, and our new
    orchestration no longer relies on them at all.  For forward-compatibility
    we simply return an empty list whenever a module provider is encountered.
    """
    return []




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
    sender_idx: int,
    state: _GatherState,
) -> None:
    """Route a provider's outputs to later recipients only.

    Only providers that appear *after* the sender in
    ``state.all_providers_list`` are considered.  This preserves the loader's
    forward-only input flow semantics expected by integration tests.
    """
    # inspect only the tail of the provider list; avoid validating against
    # earlier providers to prevent backwards propagation of values.
    for inp in inputs_list:
        for pid, _ctx, schema in state.all_providers_list[sender_idx + 1 :]:
            if not schema:
                continue
            if _schema_matches(schema, inp):
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
    module_dict: dict,
    inst: _ProviderBase | None,
    state: _GatherState,
) -> None:
    """Process a single provider entry and update ``state.received_inputs``.

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
        else _retrieve_module_inputs(
            provider_id,
            idx,
            module_dict,
            state.provider_contexts,
            state.all_providers_list,
        )
    )

    if inputs:
        # only list form is supported now; dispatch forward only
        _distribute_payloads(inputs, idx, state)


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
    """Return the provider's context model, falling back to existing context.

    This helper is no longer invoked during finalization; it remains for
    backwards-compatibility in case other callers need to recompute a model
    on the fly. The loader now prefers using the earlier-collected value from
    ``provider_contexts`` so we avoid duplicate ``create_context`` calls.
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
        # even if no inputs were received we still invoke ``finalize_context``
        # once so providers have a hook to mutate their context or perform
        # cleanup. previous versions skipped providers with empty input lists
        # which prevented legitimate side–effects; see issue #XYZ.
        inputs_schema = inst.get_inputs_schema()
        validated_inputs = _validate_raw_inputs(raw_inputs, inputs_schema)

        # derive the context object we'll hand to ``finalize_context``.
        # ``provider_contexts`` holds the value returned during the initial
        # collection pass; it may be a plain dict or, for migrated
        # class-based providers, a Pydantic model.  We prefer to re-create a
        # fresh model instance because providers frequently mutate the
        # object they return from ``create_context``.  When the provider is a
        # module adapter we *do* forward the earlier-recorded dict so module
        # factories receive the expected context.
        prev_ctx = provider_contexts.get(provider_id, {})
        if isinstance(inst, ModuleProviderAdapter):
            # adapters already have their context captured during the
            # initial collection phase; calling ``create_context`` again would
            # re-run the module code with a mutated context and produce
            # surprising results (see failing integrations).  simply reuse
            # the previously recorded dictionary.
            own_model = prev_ctx
        else:
            # for class-based providers we create a fresh model instance so
            # ``finalize_context`` receives a typed object rather than a raw
            # dict.  this mirrors the behaviour prior to refactors.
            try:
                own_model = inst.create_context()
            except Exception:  # noqa: BLE001
                own_model = prev_ctx

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
