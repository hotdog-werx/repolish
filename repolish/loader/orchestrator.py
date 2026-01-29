from pathlib import Path
from typing import Any

from .anchors import process_anchors
from .context import (
    apply_context_overrides,
    collect_contexts,
    extract_from_module_dict,
)
from .create_only import process_create_only_files
from .deletes import (
    _apply_raw_delete_items,
    process_delete_files,
)
from .mappings import process_file_mappings
from .module import get_module
from .types import Accumulators, Decision, Providers
from .validation import _validate_provider_module


def _load_module_cache(directories: list[str]) -> list[tuple[str, dict]]:
    """Load provider modules and validate them.

    Returns a list of (provider_id, module_dict) tuples.
    """
    cache: list[tuple[str, dict]] = []
    for directory in directories:
        module_path = Path(directory) / 'repolish.py'
        module_dict = get_module(str(module_path))
        provider_id = Path(directory).as_posix()
        _validate_provider_module(module_dict)
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
        process_anchors(module_dict, merged_context, accum.merged_anchors)
        process_file_mappings(
            module_dict,
            merged_context,
            accum.merged_file_mappings,
        )
        fallback_paths = process_delete_files(
            module_dict,
            merged_context,
            accum.delete_set,
        )
        process_create_only_files(
            module_dict,
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


def extract_file_mappings_from_module(
    module: str | dict[str, object],
) -> dict[str, str]:
    """Extract file mappings (dest -> source) from a module path or dict.

    Supports a callable `create_file_mappings()` returning a dict or a
    module-level `file_mappings` dict. Returns a dict mapping destination
    paths (str) to source paths (str). Entries with None values are filtered out.

    Files starting with '_repolish.' are only copied when explicitly referenced
    in the returned mappings.
    """
    module_dict = module if isinstance(module, dict) else get_module(str(module))

    fm = extract_from_module_dict(
        module_dict,
        'create_file_mappings',
        expected_type=dict,
    )
    if isinstance(fm, dict):
        # Filter out None values (means skip this destination)
        return {k: v for k, v in fm.items() if v is not None}

    raw_res = extract_from_module_dict(
        module_dict,
        'file_mappings',
        expected_type=dict,
        allow_callable=False,
    )
    if isinstance(raw_res, dict):
        return {k: v for k, v in raw_res.items() if v is not None}

    return {}


def create_providers(
    directories: list[str],
    base_context: dict[str, object] | None = None,
    context_overrides: dict[str, object] | None = None,
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
    merged_anchors: dict[str, str] = {}
    merged_file_mappings: dict[str, str] = {}
    create_only_set: set[Path] = set()
    delete_set: set[Path] = set()

    # provenance history: posix path -> list of Decision instances
    history: dict[str, list[Decision]] = {}

    module_cache = _load_module_cache(directories)
    # Collect provider contexts, allowing providers to see `merged_context`
    merged_context = collect_contexts(module_cache, initial=merged_context)
    # Apply context overrides
    if context_overrides:
        apply_context_overrides(merged_context, context_overrides)
    # Ensure project config takes final precedence
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
    )
