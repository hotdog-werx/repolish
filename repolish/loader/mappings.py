from .context import _call_factory_with_context


def _process_file_mappings(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    merged_file_mappings: dict[str, str],
) -> None:
    fm_fact = module_dict.get('create_file_mappings')
    fm: dict[str, str] | None = None
    if callable(fm_fact):
        val = _call_factory_with_context(fm_fact, merged_context)
        if isinstance(val, dict):
            fm = val
    else:
        fm_var = module_dict.get('file_mappings')
        if isinstance(fm_var, dict):
            fm = fm_var
    if isinstance(fm, dict):
        merged_file_mappings.update(
            {k: v for k, v in fm.items() if v is not None},
        )
