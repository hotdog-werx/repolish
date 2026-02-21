from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import cast

from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.types import Action, Decision, FileMode, TemplateMapping


def process_delete_files(
    provider: _ProviderBase,
    context: object,
    delete_set: set[Path],
) -> list[Path]:
    """Process a provider's delete-file contributions.

    The loader now operates on a *Provider instance* directly. The caller is
    responsible for obtaining the instance (e.g. from a module dict). This
    function extracts any ``FileMode.DELETE`` entries from
    ``provider.create_file_mappings()`` and returns a list of the corresponding
    paths. The returned list is used by the caller for the raw-delete
    fallback history; callers that do not need it can ignore the return value.
    """
    # provider is guaranteed to be a Provider; narrow for types
    inst = cast('_ProviderBase', provider)

    fm = inst.create_file_mappings(context)
    fallback_paths: list[Path] = []
    if isinstance(fm, dict):
        for k, v in fm.items():
            if isinstance(v, TemplateMapping) and v.file_mode == FileMode.DELETE:
                p = Path(*PurePosixPath(k).parts)
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
