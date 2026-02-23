import copy
from collections.abc import Callable
from dataclasses import dataclass
from inspect import isclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel as _BaseModel

from repolish.loader._log import logger
from repolish.loader.anchors import process_anchors
from repolish.loader.context import (
    apply_context_overrides,
)
from repolish.loader.create_only import process_create_only_files
from repolish.loader.deletes import (
    _apply_raw_delete_items,
    process_delete_files,
)
from repolish.loader.mappings import process_file_mappings
from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.models import ProviderEntry
from repolish.loader.module import get_module
from repolish.loader.module_loader import (
    ModuleProviderAdapter,
    collect_contexts_with_provider_map,
    inject_provider_instance_for_module,
)
from repolish.loader.three_phase import (
    build_provider_metadata,
    compute_recipient_flags,
    finalize_provider_contexts,
    gather_received_inputs,
)
from repolish.loader.types import (
    Accumulators,
    Decision,
    Providers,
    TemplateMapping,
)
from repolish.loader.validation import _validate_provider_module
from repolish.misc import ctx_to_dict


def _find_provider_class(
    module_dict: dict[str, object],
) -> type[_ProviderBase] | None:
    """Return the first Provider subclass exported in ``module_dict``.

    Keeps the detection logic isolated for easier testing and lower
    per-function complexity.
    """
    for val in module_dict.values():
        if isclass(val) and issubclass(val, _ProviderBase) and val is not _ProviderBase:
            return val
    return None


def _create_context_wrapper_for(
    inst: _ProviderBase,
) -> Callable[[dict | None], dict | None]:
    """Return a module-style `create_context` wrapper for a provider instance."""

    def _wrapper(_ctx: dict | None = None) -> dict | None:
        val = inst.create_context()
        # Accept pydantic models or dicts
        if isinstance(val, _BaseModel):
            return val.model_dump()
        return val

    return _wrapper


def _inject_provider_instance(
    module_dict: dict[str, object],
    inst: _ProviderBase,
) -> None:
    """Mutate ``module_dict`` to expose instance-backed factories."""
    # Keep a reference for diagnostics / tests
    module_dict['_repolish_provider_instance'] = inst

    # Module-level `create_context` wrapper
    module_dict['create_context'] = _create_context_wrapper_for(inst)
    module_dict['create_file_mappings'] = inst.create_file_mappings
    module_dict['create_anchors'] = inst.create_anchors


def _maybe_instantiate_provider(
    module_dict: dict[str, object],
    provider_id: str,
) -> None:
    """Instantiate and expose a Provider instance if one is exported.

    For module-style providers (no Provider subclass exported) delegate to
    `module_loader` which wraps the module into an adapter so the rest of
    the loader can treat it like a class-based provider.
    """
    cls = _find_provider_class(module_dict)
    if cls:
        inst = cls()  # Let instantiation raise if invalid (fail-fast)
        _inject_provider_instance(module_dict, inst)
        return

    # No Provider subclass — create an adapter-backed instance and inject it.
    inject_provider_instance_for_module(module_dict, provider_id)


def _load_module_cache(
    directories: list[str],
    *,
    require_file_mappings: bool = False,
) -> list[tuple[str, dict]]:
    """Load provider modules and validate them.

    Returns a list of (provider_id, module_dict) tuples.

    The ``require_file_mappings`` flag is propagated to the validator so
    callers can opt into strict enforcement of the file-mappings contract.
    """
    cache: list[tuple[str, dict]] = []
    for directory in directories:
        module_path = Path(directory) / 'repolish.py'
        module_dict = get_module(str(module_path))
        provider_id = Path(directory).as_posix()

        # Detect and instantiate class-based providers (opt-in API). If a
        # Provider subclass is exported instantiate it; otherwise let the
        # module_loader provide an adapter so downstream code can treat the
        # module uniformly as an instance-backed provider.
        _maybe_instantiate_provider(module_dict, provider_id)

        _validate_provider_module(
            module_dict,
            require_file_mappings=require_file_mappings,
            provider_id=provider_id,
        )
        cache.append((provider_id, module_dict))
    return cache


def _process_phase_two(
    module_cache: list[tuple[str, dict]],
    merged_context: dict[str, Any],
    provider_contexts: dict[str, object],
    accum: Accumulators,
) -> None:
    """Phase 2: process anchors, file mappings, delete/create-only files.

    This mutates the provided accumulators in-place.
    """
    for provider_id, module_dict in module_cache:
        # module_dict always has a provider instance injected by _load_module_cache
        inst = module_dict.get('_repolish_provider_instance')
        if not inst:
            # should not happen, but skip defensively
            continue
        inst = cast('_ProviderBase', inst)

        process_anchors(inst, merged_context, accum.merged_anchors)
        # compute file mappings once per provider and forward the result to the
        # helpers.  this avoids three separate calls to
        # ``inst.create_file_mappings()`` and decouples the helpers from the
        # provider API (making future adapter removal easier).
        own_ctx = provider_contexts.get(provider_id, {})
        fm = inst.create_file_mappings(own_ctx)
        process_file_mappings(provider_id, fm, accum)
        fallback_paths = process_delete_files(fm, accum.delete_set)
        process_create_only_files(fm, accum.create_only_set)

        # Raw delete history application (module-level raw delete_files)
        raw_items = module_dict.get('delete_files') or []
        raw_items_seq = raw_items if isinstance(raw_items, (list, tuple)) else [raw_items]
        _apply_raw_delete_items(
            accum.delete_set,
            raw_items_seq,
            fallback_paths,
            provider_id,
            accum.history,
        )


def _build_all_providers_list(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, object],
) -> list[ProviderEntry]:
    """Return the `all_providers_list` used for input routing.

    Pulling this logic into a helper reduces the complexity of the
    surrounding function and keeps the iteration simple to read.
    """
    all_providers_list: list[ProviderEntry] = []
    for idx, (pid, _mod) in enumerate(module_cache):
        schema = None
        inst = instances[idx]
        if inst is not None:
            try:
                schema = inst.get_inputs_schema()
            except Exception:  # noqa: BLE001 - don't let one provider's broken schema prevent the whole run
                # DO LATER: consider logging this error so providers can diagnose their broken schema
                schema = None
        # schema may be None if the provider does not accept inputs
        all_providers_list.append(
            (pid, ctx_to_dict(provider_contexts.get(pid)), schema),
        )
    return all_providers_list


# helper used by both override-appliers.  extracted to reduce duplication and
# make the higher-level loops easier to understand.
def _apply_overrides_to_model(
    ctx: _BaseModel,
    overrides: dict[str, object],
    provider: str | None = None,
) -> _BaseModel:
    """Return a new ``BaseModel`` with ``overrides`` applied, or the original.

    The implementation mirrors the complexity that formerly lived inline in the
    two callers.  We dump the model to a dictionary, deep-copy it (to avoid
    shared-mutable data issues), mutate the copy via
    :func:`apply_context_overrides` and then re-validate the result.  If
    validation raises or silently discards keys the user supplied we log a
    warning including the provider identifier when available.  The original
    model instance is returned on failure so the caller need not handle
    fallback logic.

    ``provider`` is used only for logging context; callers may pass ``None``.
    """
    original = ctx.model_dump()
    data = copy.deepcopy(original)
    apply_context_overrides(data, overrides)
    if data == original:
        return ctx

    try:
        new_ctx = ctx.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            'context_override_validation_failed',
            provider=provider,
            error=str(exc),
        )
        return ctx
    new_data = new_ctx.model_dump()
    if new_data != data:
        dropped = {k for k in data if k not in new_data}
        logger.warning(
            'context_override_ignored',
            provider=provider,
            ignored_keys=sorted(dropped),
        )
    return new_ctx


def _apply_overrides_to_provider_contexts(
    provider_contexts: dict[str, object],
    context_overrides: dict[str, object],
) -> None:
    """Apply configuration overrides to each provider's context.

    This handles both ``BaseModel`` and ``dict`` contexts and is used
    both before inputs are gathered and after finalization so that the
    authoritative overrides cannot be bypassed by provider logic.

    When operating on a ``BaseModel`` we convert to raw data, apply the
    overrides and then re-validate back into the same model class.  Prior to
    <2026-02> we would fall back to the raw data on validation failure,
    inadvertently turning the context into a plain ``dict``.  Because
    ``provide_inputs``/``finalize_context`` are only invoked with model
    instances this could lead to mysterious ``AttributeError`` crashes.  We
    now catch validation errors, log a warning, and retain the original
    model instance instead.  The warning makes it clear when user-supplied
    overrides could not be applied (for example, the override targets a
    field that doesn't exist yet or violates the model schema).
    """
    for pid, ctx in provider_contexts.items():
        if isinstance(ctx, _BaseModel):
            provider_contexts[pid] = _apply_overrides_to_model(
                ctx,
                context_overrides,
                provider=pid,
            )
        elif isinstance(ctx, dict):
            # cast to expected key/value types for type checker
            apply_context_overrides(
                cast('dict[str, Any]', ctx),
                context_overrides,
            )


def _apply_provider_overrides(
    provider_contexts: dict[str, object],
    provider_overrides: dict[str, dict[str, object]] | None,
) -> None:
    """Apply per-provider overrides (handles BaseModel and dict contexts).

    Extracted helper to reduce duplication in the three-phase workflow.
    Behaviour mirrors :func:`_apply_overrides_to_provider_contexts` --
    failures are logged and the original context is preserved.
    """
    if not provider_overrides:
        return

    for pid, overrides in provider_overrides.items():
        ctx = provider_contexts.get(pid)
        if isinstance(ctx, _BaseModel):
            provider_contexts[pid] = _apply_overrides_to_model(
                ctx,
                overrides,
                provider=pid,
            )
        elif isinstance(ctx, dict):
            apply_context_overrides(cast('dict[str, Any]', ctx), overrides)


@dataclass(frozen=True)
class RunThreePhaseContext:
    """Typed container for optional runtime parameters used by the three-phase provider runner."""

    base_context: dict[str, object] | None = None
    context_overrides: dict[str, object] | None = None
    provider_overrides: dict[str, dict[str, object]] | None = None


def _recompute_merged_context(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, object],
    base_context: dict[str, object] | None,
    context_overrides: dict[str, object] | None,
) -> dict[str, object]:
    """Rebuild merged_context after provider finalization.

    Extracted to lower the complexity of the main runner.
    """
    merged_context = dict(base_context or {})
    for pid, _ in module_cache:
        own = provider_contexts.get(pid, {})
        if isinstance(own, _BaseModel):
            merged_context.update(own.model_dump())
        else:
            merged_context.update(cast('dict[str, object]', own))

    if context_overrides:
        apply_context_overrides(merged_context, context_overrides)
    if base_context:
        merged_context.update(base_context)

    return merged_context


def _populate_provider_context(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, object],
) -> None:
    # before we compute schemas or apply overrides we must populate
    # ``provider_contexts`` for class-based providers.  the initial map
    # produced by ``collect_contexts_with_provider_map`` only knows about
    # module-style providers; class-based providers do not participate in the
    # first-phase merge and therefore appear as empty dicts.  this is fine for
    # finalization (where we re-create contexts explicitly) but breaks
    # ``provide_inputs`` because that hook expects a typed context object.
    #
    # we deliberately do *not* persist the result back into the merged context
    # here; the merged context is built later once the final provider contexts
    # are available.  applying overrides now ensures that both providers and
    # the merged project context see the same overridden values.

    for idx, (pid, _mod) in enumerate(module_cache):
        inst = instances[idx]
        # only class-based providers require us to synthesize a context here;
        # module-style providers (wrapped by ``ModuleProviderAdapter``) already
        # had their contexts collected during phase one using the merged
        # context.  re-calling ``create_context()`` on adapters would pass an
        # empty dict and wipe out those values, which broke several
        # integration tests.
        if (
            inst is not None
            and not isinstance(inst, ModuleProviderAdapter)
            and not isinstance(provider_contexts.get(pid), _BaseModel)
        ):
            try:
                # ``inst.create_context()`` may raise, but when it does we
                # fall back to whatever value was already in the map
                # (usually an empty dict) so we don't propagate the error.
                provider_contexts[pid] = inst.create_context()
            except Exception:  # noqa: BLE001 - we don't want one bad provider to halt
                provider_contexts[pid] = provider_contexts.get(pid, {})


def _run_three_phase(
    module_cache: list[tuple[str, dict]],
    merged_context: dict[str, object],
    provider_contexts: dict[str, object],
    options: RunThreePhaseContext | None = None,
) -> Providers:
    """Execute phase-2/3 logic and return final Providers object.

    The original implementation accepted multiple separate arguments and had
    accumulated complexity.  Bundling optional parameters into ``options``
    and extracting helpers reduces the function's signature and cognitive
    complexity while preserving behaviour.
    """
    # initialize accumulators that were previously defined at the top of
    # ``create_providers``.
    merged_anchors: dict[str, str] = {}
    merged_file_mappings: dict[str, str | TemplateMapping] = {}
    create_only_set: set[Path] = set()
    delete_set: set[Path] = set()
    history: dict[str, list[Decision]] = {}

    # gather metadata and basic helper structures
    (
        provider_migrated_map,
        instances,
    ) = build_provider_metadata(module_cache)

    _populate_provider_context(module_cache, instances, provider_contexts)

    base_context = None if options is None else options.base_context
    context_overrides = None if options is None else options.context_overrides
    provider_overrides = None if options is None else options.provider_overrides

    # apply any per-provider overrides now that each provider has a concrete
    # context object.  this ensures `provide_inputs` sees the patched values
    # even though the loader API only accepts global overrides.
    _apply_provider_overrides(provider_contexts, provider_overrides)

    # include each provider's declared input schema so that other providers can
    # inspect it when deciding what to emit.  We build the list via a
    # dedicated helper to keep this function's complexity low.
    all_providers_list: list[ProviderEntry] = _build_all_providers_list(
        module_cache,
        instances,
        provider_contexts,
    )

    # apply overrides before input gathering
    if context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            context_overrides,
        )

    # we no longer attempt to predict receivers; just call all providers
    # for their outgoing inputs and route them based on schemas.
    received_inputs = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        # old flag still passed for compatibility but ignored
        compute_recipient_flags(instances),
    )

    # finalize provider contexts based on collected inputs
    finalize_provider_contexts(
        module_cache,
        instances,
        received_inputs,
        provider_contexts,
        all_providers_list,
    )

    # re-apply global overrides after finalization
    if context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            context_overrides,
        )

    # and likewise re-apply per-provider overrides so the contexts exposed
    # in the returned `Providers` object include any project-supplied values.
    _apply_provider_overrides(provider_contexts, provider_overrides)

    # recompute merged_context after finalization
    merged_context = _recompute_merged_context(
        module_cache,
        provider_contexts,
        base_context,
        context_overrides,
    )

    accum = Accumulators(
        merged_anchors=merged_anchors,
        merged_file_mappings=merged_file_mappings,
        create_only_set=create_only_set,
        delete_set=delete_set,
        history=history,
    )
    _process_phase_two(module_cache, merged_context, provider_contexts, accum)

    return Providers(
        context=merged_context,
        anchors=accum.merged_anchors,
        delete_files=list(accum.delete_set),
        file_mappings=accum.merged_file_mappings,
        create_only_files=list(accum.create_only_set),
        delete_history=accum.history,
        provider_contexts=provider_contexts,
        provider_migrated=provider_migrated_map,
    )


def create_providers(
    directories: list[str],
    base_context: dict[str, object] | None = None,
    context_overrides: dict[str, object] | None = None,
    *,
    provider_overrides: dict[str, dict[str, object]] | None = None,
    require_file_mappings: bool = False,
) -> Providers:
    """Load all template providers and merge their contributions.

    Merging semantics:
    - context: dicts are merged in order; later providers override earlier keys.
    - anchors: dicts are merged in order; later providers override earlier keys.
    - file_mappings: dicts are merged in order; later providers override earlier keys.
    - create_only_files: lists are merged; later providers can add more files.
    - delete_files: providers supply Path entries; an entry prefixed with a
      leading '!' (literal leading char in the original string) will act as an
      undo for that path (i.e., prevent deletion). The loader will apply
      additions/removals in provider order.
    """
    # Two-phase load: first collect contexts (allowing providers to see
    # a base context if provided), then call other factories with the
    # fully merged context so factories can make decisions based on it.
    # Seed merged context with project-level config when provided so
    # provider factories see project values during their `create_context()`
    # calls. Providers may modify the merged context during collection, but
    # we re-apply `base_context` afterwards so project config wins as the
    # final override.
    merged_context: dict[str, object] = dict(base_context or {})
    # other accumulators are handled by Accumulators object below

    module_cache = _load_module_cache(
        directories,
        require_file_mappings=require_file_mappings,
    )
    # Collect provider contexts (also capture per-provider contexts)
    merged_context, provider_contexts = collect_contexts_with_provider_map(
        module_cache,
        initial=merged_context,
    )

    # hand off the remainder of the workflow to a helper that encapsulates
    # the three-phase input/finalization logic plus related metadata tracking.
    return _run_three_phase(
        module_cache,
        merged_context,
        provider_contexts,
        RunThreePhaseContext(
            base_context=base_context,
            context_overrides=context_overrides,
            provider_overrides=provider_overrides,
        ),
    )
