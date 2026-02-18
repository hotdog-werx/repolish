from typing import cast

from .context import call_factory_with_context


def _resolve_file_mappings(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
) -> dict[str, object] | None:
    """Return the provider's file mappings dict or None.

    Prefer `create_file_mappings()` when present; otherwise fall back to the
    module-level `file_mappings` variable.
    """
    fm_fact = module_dict.get('create_file_mappings')
    if callable(fm_fact):
        val = call_factory_with_context(fm_fact, merged_context)
        return cast('dict[str, object]', val) if isinstance(val, dict) else None

    fm_var = module_dict.get('file_mappings')
    return cast('dict[str, object]', fm_var) if isinstance(fm_var, dict) else None


def _is_valid_mapping_value(v: object) -> bool:
    """Return True for accepted mapping values (str or (str, dict))."""
    return isinstance(v, str) or (
        isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], dict)
    )


def process_file_mappings(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    merged_file_mappings: dict[str, str | tuple[str, dict]],
) -> None:
    """Process a provider's file mapping contributions and merge.

    Accepts either a callable `create_file_mappings()` or a module-level
    `file_mappings` dict. The mapping value may be either:
      - `str` (existing behavior) -> source path in template output
      - `tuple[str, dict]` -> (source_template, extra_context)
    Entries with `None` values are filtered out.
    """
    fm = _resolve_file_mappings(module_dict, merged_context)
    if not isinstance(fm, dict):
        return

    # keep tuple values as-is (they will be rendered later in hydration)
    for k, v in fm.items():
        if v is None:
            continue
        if _is_valid_mapping_value(v):
            merged_file_mappings[k] = cast('str | tuple[str, dict]', v)
