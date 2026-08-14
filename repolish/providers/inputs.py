from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel as _BaseModel
from pydantic_core import ValidationError

from repolish.providers._log import logger
from repolish.providers.models import (
    BaseContext,
    BaseInputs,
    ProvideInputsOptions,
    ProviderEntry,
    call_provider_method,
)
from repolish.providers.models import (
    Provider as _ProviderBase,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


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
        raw = call_provider_method(
            inst,
            'provide_inputs',
            ProvideInputsOptions(
                own_context=own_model,
                all_providers=all_providers_list,
                provider_index=idx,
            ),
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


def _route_input_to_targets(
    inp: object,
    targets: list[ProviderEntry],
    received_inputs: dict[str, list[BaseInputs]],
) -> None:
    """Route a single payload to every target whose schema matches it."""
    for entry in targets:
        schema = entry.input_type
        if schema and _schema_matches(schema, inp):
            received_inputs.setdefault(entry.provider_id, []).append(
                cast('BaseInputs', inp),
            )


def _distribute_payloads(
    inputs_list: Sequence[object],
    state: _GatherState,
) -> None:
    """Route a provider's outputs to every other provider.

    Every payload is delivered to all providers regardless of position;
    schema filtering ensures unrelated providers are not burdened with
    irrelevant objects.

    Routing targets are the *local* providers only (``state.routing_list``).
    Extra member entries in ``state.all_providers_list`` are present for
    inspection by ``provide_inputs`` / ``finalize_context`` but must not
    receive routed inputs — doing so would produce duplicate entries in
    ``received_inputs`` when member entries share a ``provider_id`` with a
    root provider.
    """
    targets = state.routing_list if state.routing_list is not None else state.all_providers_list
    for inp in inputs_list:
        _route_input_to_targets(inp, targets, state.received_inputs)


@dataclass
class _GatherState:
    provider_contexts: dict[str, BaseContext]
    all_providers_list: list[ProviderEntry]
    received_inputs: dict[str, list[BaseInputs]]
    routing_list: list[ProviderEntry] | None = None
    """Subset of ``all_providers_list`` used as routing targets.

    When ``None``, ``all_providers_list`` is used directly.  Set to the
    local (root-pass) provider entries only during a monorepo root pass so
    that extra member entries do not cause duplicate input accumulation.
    """


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


def collect_all_emitted_inputs(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, BaseContext],
    all_providers_list: list[ProviderEntry],
) -> list[BaseInputs]:
    """Call each provider's ``provide_inputs`` and return all outputs as a flat list.

    Unlike :func:`gather_received_inputs`, this function does **not** route the
    inputs to recipients.  It is used by the dry-pass logic to capture the raw
    outputs before any routing occurs.
    """
    flat: list[BaseInputs] = []
    for idx, (provider_id, _) in enumerate(module_cache):
        inst = instances[idx]
        if not inst:
            continue
        raw = _retrieve_instance_inputs(
            provider_id,
            idx,
            inst,
            provider_contexts,
            all_providers_list,
        )
        if raw:
            flat.extend(cast('list[BaseInputs]', raw))
    return flat


def gather_received_inputs(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, BaseContext],
    all_providers_list: list[ProviderEntry],
    extra_inputs: list[BaseInputs] | None = None,
) -> dict[str, list[BaseInputs]]:
    """Collect provider inputs, route them, and return a by-recipient mapping.

    When *extra_inputs* is provided those inputs are added to the routing pool
    alongside the locally-emitted inputs.  This is how member providers' outputs
    are delivered to root providers during a monorepo root pass.

    Routing is restricted to the *local* providers (those in ``module_cache``).
    Extra member entries in ``all_providers_list`` are for inspection only and
    must not be routing targets — doing so would produce duplicate entries in
    ``received_inputs`` when member providers share a ``provider_id`` with a
    root provider.
    """
    # The first `len(module_cache)` entries in `all_providers_list` are always
    # the local (root-pass) providers built from `module_cache`.  Extra member
    # entries are appended *after* them by the orchestrator.  Slicing avoids
    # the shared-`provider_id` trap: installed packages used by both root and
    # members have identical `provider_id` strings, so filtering by pid would
    # include duplicate member entries and cause 3x duplication in
    # `received_inputs`.
    routing_list = all_providers_list[: len(module_cache)]
    state = _GatherState(
        provider_contexts=provider_contexts,
        all_providers_list=all_providers_list,
        received_inputs={},
        routing_list=routing_list,
    )

    for idx, (provider_id, _) in enumerate(module_cache):
        _collect_for_provider(
            idx,
            provider_id,
            instances[idx],
            state,
        )

    if extra_inputs:
        _distribute_payloads(extra_inputs, state)

    return state.received_inputs
