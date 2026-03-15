from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, cast

from pydantic import BaseModel as _BaseModel
from pydantic_core import ValidationError

from repolish.loader._log import logger
from repolish.loader.models import (
    Accumulators,
    Action,
    BaseContext,
    BaseInputs,
    Decision,
    FileMode,
    GlobalContext,
    ProviderEntry,
    ProviderInfo,
    TemplateMapping,
    get_global_context,
)
from repolish.loader.models import Provider as _ProviderBase
from repolish.pkginfo import resolve_package_identity


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
            accum.merged_file_mappings[dest] = src
            continue
        annotated = TemplateMapping(
            source_template=src.source_template,
            extra_context=src.extra_context,
            file_mode=src.file_mode,
            source_provider=provider_id,
        )
        _apply_annotated_tm(dest, annotated, provider_id, accum)


def _collect_provider_contributions(
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
        val = inst.create_anchors(own_ctx)
        if val:
            if not isinstance(val, dict):
                msg = 'create_anchors() must return a dict'
                raise TypeError(msg)
            accum.merged_anchors.update(cast('dict[str, str]', val))
        fm = inst.create_file_mappings(own_ctx)
        _process_provider_fm(provider_id, fm, accum)


# ---------------------------------------------------------------------------
# Provider pipeline setup helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineOptions:
    """Typed container for optional runtime parameters for the provider pipeline."""

    context_overrides: dict[str, object] | None = None
    provider_overrides: dict[str, dict[str, object]] | None = None
    alias_map: dict[str, str] | None = None  # provider_id -> config alias
    global_context: GlobalContext = field(default_factory=GlobalContext)


def _build_all_providers_list(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, BaseContext],
    *,
    alias_map: dict[str, str] | None = None,
) -> list[ProviderEntry]:
    """Return the `all_providers_list` used for input routing.

    Pulling this logic into a helper reduces the complexity of the
    surrounding function and keeps the iteration simple to read.
    """
    all_providers_list: list[ProviderEntry] = []
    for idx, (pid, _mod) in enumerate(module_cache):
        schema = None
        inst = instances[idx]
        alias: str | None = None
        inst_type: type[Any] | None = None
        ctx_obj = provider_contexts.get(pid)
        ctx_type: type[BaseContext] | None = None

        if inst is not None:
            try:
                schema = inst.get_inputs_schema()
            except Exception:  # noqa: BLE001 - don't let one provider's broken schema prevent the whole run
                # DO LATER: consider logging this error so providers can diagnose their broken schema
                schema = None
            # `alias` is the configuration key (here we mirror provider_id
            # since that's what create_providers passes).
            alias = pid
            inst_type = type(inst)

        # if context object is a BaseModel we remember its class
        if isinstance(ctx_obj, BaseContext):
            ctx_type = type(ctx_obj)

        # if an alias map was provided, prefer it over the default
        # value we computed earlier.
        if alias_map is not None and pid in alias_map:
            alias = alias_map[pid]

        all_providers_list.append(
            ProviderEntry(
                provider_id=pid,
                alias=alias,
                inst_type=inst_type,
                context=ctx_obj or BaseContext(),
                context_type=ctx_type,
                input_type=schema,
            ),
        )
    return all_providers_list


def _synthesize_provider_context_for_pid(
    inst: _ProviderBase,
    pid: str,
    provider_contexts: dict[str, BaseContext],
    global_context: GlobalContext,
) -> None:
    """Ensure `provider_contexts[pid]` contains a typed context for class-based providers.

    Call `create_context`, fall back to existing value on error, and
    inject the shared `GlobalContext` into provider contexts that declare
    a `repolish` field (i.e. subclasses of `BaseContext`).
    """
    if isinstance(provider_contexts.get(pid), BaseContext):
        return

    try:
        # create_context is generic but its bound by BaseContext
        ctx = cast('BaseContext', inst.create_context())
    except Exception as exc:  # noqa: BLE001 - don't let one provider stop the run
        logger.warning(
            'provider_create_context_raised',
            provider=pid,
            error=str(exc),
        )
        return

    if isinstance(ctx, BaseContext) and hasattr(ctx, 'repolish'):
        ctx = ctx.model_copy(update={'repolish': global_context})

    # inject provider identity so templates can reference {{ _provider.alias }},
    # {{ _provider.version }}, {{ _provider.package_name }}, etc. without the
    # provider having to do it manually.
    if isinstance(ctx, BaseContext):
        ctx._provider_data = ProviderInfo(
            alias=getattr(inst, 'alias', ''),
            version=getattr(inst, 'version', ''),
            package_name=getattr(inst, 'package_name', ''),
            project_name=getattr(inst, 'project_name', ''),
        )

    provider_contexts[pid] = ctx


def _populate_provider_context(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, BaseContext],
    global_context: GlobalContext,
) -> None:
    """Populate `provider_contexts` with typed context objects for each provider.

    Must run before schemas are inspected or overrides applied so that
    `provide_inputs` receives a typed context object rather than an empty
    placeholder.
    """
    for idx, (pid, _mod) in enumerate(module_cache):
        inst = instances[idx]
        if inst is None:  # pragma: no cover - module-style providers have no class instance
            continue
        _synthesize_provider_context_for_pid(
            inst,
            pid,
            provider_contexts,
            global_context,
        )


def _set_provider_metadata(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    alias_map: dict[str, str],
) -> None:
    """Set alias, version, package_name and project_name on every provider instance.

    Version is read from the module's __version__ when present; falls back to
    an empty string for local / un-installed providers.
    package_name and project_name are derived from __package__ via
    :func:`repolish.pkginfo.resolve_package_identity`.
    """
    for _idx, (_pid, _mod) in enumerate(module_cache):
        _inst = instances[_idx]
        if _inst is not None:
            _inst.alias = alias_map.get(_pid, _pid)
            _inst.version = _mod.get('__version__', '') or ''
            _pkg, _proj = resolve_package_identity(_mod.get('__package__'))
            _inst.package_name = _pkg
            _inst.project_name = _proj
