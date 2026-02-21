from collections.abc import Callable
from inspect import isclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel as _BaseModel

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
from repolish.loader.module import get_module
from repolish.loader.module_loader import (
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
        process_file_mappings(
            provider_id,
            inst,
            merged_context,
            accum,
        )
        fallback_paths = process_delete_files(
            inst,
            merged_context,
            accum.delete_set,
        )
        process_create_only_files(
            inst,
            merged_context,
            accum.create_only_set,
        )

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


def _run_three_phase(
    module_cache: list[tuple[str, dict]],
    merged_context: dict[str, object],
    provider_contexts: dict[str, dict[str, object]],
    base_context: dict[str, object] | None,
    context_overrides: dict[str, object] | None,
) -> Providers:
    """Execute phase-2/3 logic and return final Providers object.

    This helper encapsulates the complex provider-input collection,
    finalization, context recomputation and override application that was
    previously implemented inline in :func:`create_providers`.  Metadata maps
    such as ``provider_migrated_map`` are constructed via helpers imported from
    ``three_phase``.
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
        canonical_name_to_pid,
    ) = build_provider_metadata(module_cache)

    all_providers_list = [(pid, provider_contexts.get(pid, {})) for pid, _ in module_cache]
    has_recipient_after = compute_recipient_flags(instances)
    received_inputs = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        canonical_name_to_pid,
        has_recipient_after,
    )

    # finalize provider contexts based on collected inputs
    finalize_provider_contexts(
        module_cache,
        instances,
        received_inputs,
        provider_contexts,
        all_providers_list,
    )

    # recompute merged_context after finalization
    merged_context = dict(base_context or {})
    for pid, _ in module_cache:
        merged_context.update(provider_contexts.get(pid, {}))

    if context_overrides:
        apply_context_overrides(merged_context, context_overrides)
    if base_context:
        merged_context.update(base_context)

    accum = Accumulators(
        merged_anchors=merged_anchors,
        merged_file_mappings=merged_file_mappings,
        create_only_set=create_only_set,
        delete_set=delete_set,
        history=history,
    )
    _process_phase_two(module_cache, merged_context, accum)

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
        base_context,
        context_overrides,
    )
