from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel as _BaseModel
from pydantic_core import ValidationError

from repolish.providers._log import logger
from repolish.providers.models import (
    Accumulators,
    Action,
    BaseContext,
    BaseInputs,
    Decision,
    FileMode,
    FinalizeContextOptions,
    GlobalContext,
    ProvideInputsOptions,
    ProviderEntry,
    ProviderInfo,
    TemplateMapping,
    call_provider_method,
    get_global_context,
)
from repolish.providers.models import Provider as _ProviderBase
from repolish.providers.models.context import RepolishContext

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
        for entry in targets:
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


# ---------------------------------------------------------------------------
# Accumulator helpers (file-mapping / anchor collection)
# ---------------------------------------------------------------------------


def _apply_annotated_tm(
    dest: str,
    annotated: TemplateMapping,
    provider_id: str,
    accum: Accumulators,
) -> None:
    """Apply a fully-annotated TemplateMapping to the accumulators."""
    path = Path(*PurePosixPath(dest).parts)
    key = path.as_posix()
    if annotated.file_mode == FileMode.DELETE:
        accum.delete_set.add(path)
        accum.merged_file_mappings.pop(dest, None)
        accum.history.setdefault(key, []).append(
            Decision(source=provider_id, action=Action.delete),
        )
    elif annotated.file_mode == FileMode.KEEP:
        accum.delete_set.discard(path)
        accum.history.setdefault(key, []).append(
            Decision(source=provider_id, action=Action.keep),
        )
    elif annotated.file_mode == FileMode.SUPPRESS:
        # Don't render or stage this file; record the source template path so
        # the renderer can skip it even if it was staged by another provider.
        if annotated.source_template:
            accum.suppressed_sources.add(annotated.source_template)
        accum.merged_file_mappings.pop(dest, None)
    else:
        if annotated.file_mode == FileMode.CREATE_ONLY:
            accum.create_only_set.add(path)
        accum.merged_file_mappings[dest] = annotated


def _process_provider_fm(
    provider_id: str,
    fm: dict[str, str | TemplateMapping | None],
    accum: Accumulators,
) -> None:
    """Process one provider's file_mappings in a single pass.

    Handles all modes in order: plain string sources, DELETE, KEEP,
    CREATE_ONLY, and REGULAR entries.  Populates `merged_file_mappings`,
    `delete_set`, `create_only_set`, and `history` on `accum`.
    """
    for dest, src in fm.items():
        if src is None:
            # the provider explicitly opted out of this template path; record
            # it so the builder can exclude it from auto-staging.
            accum.suppressed_sources.add(dest)
            continue
        if isinstance(src, str):
            # Wrap plain-string sources in a TemplateMapping so they carry
            # source_provider.  This lets build_file_records attribute the
            # destination file to the correct provider instead of falling
            # back to 'unknown'.  get_source_str_from_mapping and all other
            # consumers already handle both str and TemplateMapping values.
            accum.merged_file_mappings[dest] = TemplateMapping(
                source_template=src,
                source_provider=provider_id,
            )
            continue
        annotated = TemplateMapping(
            source_template=src.source_template,
            extra_context=src.extra_context,
            file_mode=src.file_mode,
            source_provider=provider_id,
        )
        _apply_annotated_tm(dest, annotated, provider_id, accum)


def collect_provider_contributions(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    accum: Accumulators,
) -> None:
    """Collect anchors, file mappings, and delete/create-only decisions from all providers.

    This mutates the provided accumulators in-place.
    """
    for provider_id, module_dict in module_cache:
        # module_dict always has a provider instance injected by _load_module_cache
        inst = module_dict.get('_repolish_provider_instance')
        if not inst:
            # should not happen, but skip defensively
            continue
        inst = cast('_ProviderBase', inst)

        own_ctx = provider_contexts.get(provider_id, {})
        if not isinstance(own_ctx, BaseContext):
            continue
        val = call_provider_method(inst, 'create_anchors', own_ctx)
        if val:
            if not isinstance(val, dict):
                msg = 'create_anchors() must return a dict'
                raise TypeError(msg)
            accum.merged_anchors.update(cast('dict[str, str]', val))
        fm = cast(
            'dict[str, str | TemplateMapping | None]',
            call_provider_method(inst, 'create_file_mappings', own_ctx),
        )
        _process_provider_fm(provider_id, fm, accum)

        # Collect promote_file_mappings only in member mode.
        workspace_mode = own_ctx.repolish.workspace.mode
        if workspace_mode == 'member':
            pfm = cast(
                'dict[str, str | TemplateMapping | None]',
                call_provider_method(inst, 'promote_file_mappings', own_ctx),
            )
            if pfm:
                # Wrap plain strings, annotate source_provider, fold into accum.
                for dest, src in pfm.items():
                    if src is None:
                        continue
                    if isinstance(src, str):
                        accum.promoted_file_mappings[dest] = TemplateMapping(
                            source_template=src,
                            source_provider=provider_id,
                        )
                    else:
                        accum.promoted_file_mappings[dest] = TemplateMapping(
                            source_template=src.source_template,
                            extra_context=src.extra_context,
                            file_mode=src.file_mode,
                            promote_conflict=src.promote_conflict,
                            source_provider=provider_id,
                        )
        elif workspace_mode in ('root', 'standalone'):
            # Calling promote_file_mappings in non-member mode is a mistake;
            # warn but don't halt the run.
            pfm_check = cast(
                'dict[str, str | TemplateMapping | None]',
                call_provider_method(inst, 'promote_file_mappings', own_ctx),
            )
            if pfm_check:
                logger.warning(
                    'promote_file_mappings_ignored_in_non_member_mode',
                    provider=provider_id,
                    mode=workspace_mode,
                    suggestion='promote_file_mappings is only effective in member mode',
                )
