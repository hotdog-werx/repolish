from pathlib import Path, PurePosixPath

from .context import _call_factory_with_context, _extract_from_module_dict
from .deletes import _normalize_delete_iterable
from .module import get_module


def _process_create_only_files(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    create_only_set: set[Path],
) -> None:
    co_fact = module_dict.get('create_create_only_files')
    val: object | None
    if callable(co_fact):
        val = _call_factory_with_context(co_fact, merged_context)
    else:
        val = module_dict.get('create_only_files')

    if not isinstance(val, (list, tuple, set)):
        return

    for it in val:
        if isinstance(it, str):
            p = Path(*PurePosixPath(it).parts)
            create_only_set.add(p)
        elif isinstance(it, Path):
            create_only_set.add(it)


def extract_create_only_files_from_module(
    module: str | dict[str, object],
) -> list[str]:
    """Extract create-only file paths from a module path or dict.

    Supports a callable `create_create_only_files()` returning a list/iterable
    or a module-level `create_only_files` list/iterable.

    These files are only copied if they don't already exist in the destination,
    allowing template-provided initial files without overwriting user changes.

    Returns a list of file paths (as strings).
    """
    module_dict = module if isinstance(module, dict) else get_module(str(module))

    # Try callable first
    result = _extract_from_module_dict(
        module_dict,
        'create_create_only_files',
        expected_type=(list, tuple, set),
    )
    if isinstance(result, (list, tuple, set)):
        return _normalize_delete_iterable(result)

    # Fall back to module-level variable
    raw_res = _extract_from_module_dict(
        module_dict,
        'create_only_files',
        expected_type=(list, tuple, set),
        allow_callable=False,
    )
    raw = raw_res if isinstance(raw_res, (list, tuple, set)) else []
    return _normalize_delete_iterable(raw)
