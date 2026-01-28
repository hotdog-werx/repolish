from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from .context import call_factory_with_context, extract_from_module_dict
from .module import get_module
from .types import Action, Decision


def process_delete_files(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    delete_set: set[Path],
) -> list[Path]:
    """Process a provider's delete-file contributions.

    Supports a callable `create_delete_files()` returning a list/tuple or a
    module-level `delete_files`. Returns a list of normalized `Path` objects
    that can be used as fallbacks for raw module-level delete entries.
    """
    df_fact = module_dict.get('create_delete_files')
    df: list | tuple | None = None
    fallback_paths: list[Path] = []
    if callable(df_fact):
        val = call_factory_with_context(df_fact, merged_context)
        if val is None:
            df = []
        elif not isinstance(val, (list, tuple)):
            msg = 'create_delete_files() must return a list or tuple'
            raise TypeError(msg)
        else:
            df = val
    else:
        df_var = module_dict.get('delete_files')
        if isinstance(df_var, (list, tuple)):
            df = df_var

    if callable(df_fact) and isinstance(df, (list, tuple)):
        norm = _normalize_delete_iterable(df)
        for it in norm:
            p = Path(*PurePosixPath(it).parts)
            delete_set.add(p)
            fallback_paths.append(p)
    return fallback_paths


def normalize_delete_items(items: Iterable[str]) -> list[Path]:
    """Normalize delete file entries (POSIX strings) to platform-native Paths.

    The helper `extract_delete_items_from_module` already normalizes provider
    outputs (including Path-like objects) to POSIX strings. This function now
    expects strings and will raise TypeError for any other type (fail-fast).
    """
    paths: list[Path] = []
    for it in items:
        # Accept strings only; other types are errors in fail-fast mode
        if isinstance(it, str):
            p = Path(*PurePosixPath(it).parts)
            paths.append(p)
            continue
        msg = f'Invalid delete_files entry: {it!r}'
        raise TypeError(msg)
    return paths


def normalize_delete_item(item: object) -> str | None:
    """Normalize a single delete entry to a POSIX string.

    Accepts `Path` and `str`. Raises `TypeError` for other types (fail-fast).
    Returns the POSIX string or `None` when the input is falsy.
    """
    # Accept real Path objects
    if isinstance(item, Path):
        return item.as_posix()
    if isinstance(item, str):
        return item
    # Anything else is an explicit error in fail-fast mode
    msg = f'Invalid delete_files entry: {item!r}'
    raise TypeError(msg)


def _normalize_delete_iterable(items: Iterable[object]) -> list[str]:
    """Normalize an iterable of delete items (Path or str) to POSIX strings.

    Returns an empty list for non-iterables or when no valid items are found.
    """
    out: list[str] = []
    if not items:
        return out
    # Iteration errors should propagate (fail-fast)
    for it in items:
        n = normalize_delete_item(it)
        if n:
            out.append(n)
    return out


def extract_delete_items_from_module(
    module: str | dict[str, object],
) -> list[str]:
    """Extract raw delete-file entries (POSIX strings) from a module path or dict.

    Supports a callable `create_delete_files()` returning a list/tuple or a
    module-level `delete_files`. Returns a list of POSIX-style strings. Exceptions
    are logged and the function returns an empty list on failure.
    """
    module_dict = module if isinstance(module, dict) else get_module(str(module))

    df = extract_from_module_dict(
        module_dict,
        'create_delete_files',
        expected_type=(list, tuple),
    )
    # df may be None or a list/tuple — only treat it as iterable when it's
    # actually a sequence. This narrows the type for the static checker.
    if isinstance(df, (list, tuple)):
        # Normalization raises on bad entries in fail-fast mode
        return _normalize_delete_iterable(df)

    raw_res = extract_from_module_dict(
        module_dict,
        'delete_files',
        expected_type=(list, tuple),
        allow_callable=False,
    )
    raw = raw_res if isinstance(raw_res, (list, tuple)) else []
    return _normalize_delete_iterable(raw)


def _apply_raw_delete_items(
    delete_set: set[Path],
    raw_items: Iterable[object],
    fallback: list[Path],
    provider_id: str,
    history: dict[str, list[Decision]],
) -> None:
    """Apply provider-supplied raw delete items to the delete_set.

    raw_items: the original module-level `delete_files` value (may contain
    '!' prefixed strings to indicate negation). fallback: normalized Path list
    produced when a provider returned create_delete_files().
    """
    # Normalize raw_items (they may contain Path objects when defined at
    # module-level). Prefer normalized raw_items; if none, fall back to the
    # normalized fallback produced from create_delete_files().
    # Collect normalized delete-strings from raw_items (fail-fast if a
    # normalizer raises). Use a comprehension to reduce branching.
    items = [n for it in raw_items for n in (normalize_delete_item(it),) if n] if raw_items else []

    # If provider didn't supply module-level raw items, fall back to the
    # normalized list produced from create_delete_files().
    if not items:
        items = [p.as_posix() for p in fallback]

    for raw in items:
        neg = raw.startswith('!')
        entry = raw[1:] if neg else raw
        p = Path(*PurePosixPath(entry).parts)
        key = p.as_posix()
        # record provenance for this provider decision
        history.setdefault(key, []).append(
            Decision(
                source=provider_id,
                action=(Action.keep if neg else Action.delete),
            ),
        )
        # single call selected by neg flag (discard is a no-op if missing)
        (delete_set.discard if neg else delete_set.add)(p)
