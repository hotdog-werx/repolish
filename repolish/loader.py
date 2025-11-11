from collections.abc import Iterable
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path, PurePosixPath

from hotlog import get_logger
from pydantic import BaseModel, Field

logger = get_logger(__name__)


class Action(str, Enum):
    """Enumeration of possible actions for a path."""

    delete = 'delete'
    keep = 'keep'


class Decision(BaseModel):
    """Typed provenance decision recorded for each path.

    - source: provider identifier (POSIX string)
    - action: Action enum
    """

    source: str
    action: Action


class Providers(BaseModel):
    """Structured provider contributions collected from template modules.

    - context: merged cookiecutter context
    - anchors: merged anchors mapping
    - delete_files: list of Paths representing files to delete
    - file_mappings: dict mapping destination paths to source paths in template
    - create_only_files: list of Paths for files that should only be created if they don't exist
    """

    context: dict[str, object] = Field(default_factory=dict)
    anchors: dict[str, str] = Field(default_factory=dict)
    delete_files: list[Path] = Field(default_factory=list)
    file_mappings: dict[str, str] = Field(default_factory=dict)
    create_only_files: list[Path] = Field(default_factory=list)
    # provenance mapping: posix path -> list of Decision instances
    delete_history: dict[str, list[Decision]] = Field(default_factory=dict)


def get_module(module_path: str) -> dict[str, object]:
    """Dynamically import a module from a given path."""
    spec = spec_from_file_location('repolish_module', module_path)
    if not spec or not spec.loader:  # pragma: no cover
        # We shouldn't reach this point in tests due to other validations
        msg = f'Cannot load module from path: {module_path}'
        raise ImportError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.__dict__


def _normalize_delete_items(items: Iterable[str]) -> list[Path]:
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


def _extract_from_module_dict(
    module_dict: dict[str, object],
    name: str,
    *,
    expected_type: type | tuple[type, ...] | None = None,
    allow_callable: bool = True,
    default: object | None = None,
) -> object | None:
    """Generic extractor for attributes or factory callables from a module dict.

    - If the module defines a callable named `name` and `allow_callable` is True,
      it will be invoked and its return value validated against `expected_type`.
    - Otherwise, if the module has a top-level attribute with `name`, that
      value will be returned if it matches `expected_type` (when provided).
    - On any mismatch or exception the `default` is returned.
    """
    # Prefer a callable factory when present and allowed
    candidate = module_dict.get(name)
    if allow_callable and callable(candidate):
        # If the factory raises, let the exception propagate (fail-fast)
        val = candidate()
        if expected_type is None or isinstance(val, expected_type):
            return val
        msg = f'{name}() returned wrong type: {type(val)!r}'
        raise TypeError(msg)

    # Fallback to module-level value
    if candidate is None:
        return default
    if expected_type is None or isinstance(candidate, expected_type):
        return candidate
    msg = f'module attribute {name!r} has wrong type: {type(candidate)!r}'
    raise TypeError(msg)


def extract_context_from_module(
    module: str | dict[str, object],
) -> dict[str, object] | None:
    """Extract cookiecutter context from a module (path or dict).

    Accepts either a module path (str) or a preloaded module dict. Returns a
    dict or None if not present/invalid.
    """
    module_dict = module if isinstance(module, dict) else get_module(str(module))
    ctx = _extract_from_module_dict(
        module_dict,
        'create_context',
        expected_type=dict,
    )
    if isinstance(ctx, dict):
        return ctx
    # Also accept a module-level `context` variable for compatibility
    ctx2 = _extract_from_module_dict(
        module_dict,
        'context',
        expected_type=dict,
        allow_callable=False,
    )
    if isinstance(ctx2, dict):
        return ctx2
    # Missing context is not an error; return None to indicate absence
    logger.warning(
        'create_context_not_found',
        module=(module if isinstance(module, str) else '<module_dict>'),
    )
    return None


def extract_anchors_from_module(
    module: str | dict[str, object],
) -> dict[str, str]:
    """Extract anchors mapping from a template module (path or dict).

    Supports either a callable `create_anchors()` or a module-level `anchors` dict.
    Returns an empty dict on failure.
    """
    module_dict = module if isinstance(module, dict) else get_module(str(module))
    anchors = _extract_from_module_dict(
        module_dict,
        'create_anchors',
        expected_type=dict,
    )
    if isinstance(anchors, dict):
        return anchors
    a_obj = _extract_from_module_dict(
        module_dict,
        'anchors',
        expected_type=dict,
        allow_callable=False,
    )
    if isinstance(a_obj, dict):
        return a_obj
    # Absence of anchors is fine; return empty mapping
    return {}


def _normalize_delete_item(item: object) -> str | None:
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
        n = _normalize_delete_item(it)
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

    df = _extract_from_module_dict(
        module_dict,
        'create_delete_files',
        expected_type=(list, tuple),
    )
    # df may be None or a list/tuple — only treat it as iterable when it's
    # actually a sequence. This narrows the type for the static checker.
    if isinstance(df, (list, tuple)):
        # Normalization raises on bad entries in fail-fast mode
        return _normalize_delete_iterable(df)

    raw_res = _extract_from_module_dict(
        module_dict,
        'delete_files',
        expected_type=(list, tuple),
        allow_callable=False,
    )
    raw = raw_res if isinstance(raw_res, (list, tuple)) else []
    return _normalize_delete_iterable(raw)


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

    fm = _extract_from_module_dict(
        module_dict,
        'create_file_mappings',
        expected_type=dict,
    )
    if isinstance(fm, dict):
        # Filter out None values (means skip this destination)
        return {k: v for k, v in fm.items() if v is not None}

    raw_res = _extract_from_module_dict(
        module_dict,
        'file_mappings',
        expected_type=dict,
        allow_callable=False,
    )
    if isinstance(raw_res, dict):
        return {k: v for k, v in raw_res.items() if v is not None}

    return {}


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
    items = [n for it in raw_items for n in (_normalize_delete_item(it),) if n] if raw_items else []

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


def _process_provider_dict(  # noqa: PLR0913 - helper function with many args
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    merged_anchors: dict[str, str],
    merged_file_mappings: dict[str, str],
    create_only_set: set[Path],
    delete_set: set[Path],
    provider_id: str,
    history: dict[str, list[Decision]],
) -> None:
    """Merge a loaded provider module's contributions into the accumulators.

    This helper operates on a preloaded module dict so callers can handle
    loading and error handling separately.
    """
    ctx = extract_context_from_module(module_dict) or {}
    anchors = extract_anchors_from_module(module_dict) or {}
    file_mappings = extract_file_mappings_from_module(module_dict) or {}
    raw_delete_items = extract_delete_items_from_module(module_dict)
    delete_files = _normalize_delete_items(raw_delete_items)
    raw_create_only_items = extract_create_only_files_from_module(module_dict)
    create_only_files = _normalize_delete_items(raw_create_only_items)

    if ctx:
        merged_context.update(ctx)
    if anchors:
        merged_anchors.update(anchors)
    if file_mappings:
        merged_file_mappings.update(file_mappings)

    # Add create_only_files to the set (later providers can add more)
    for path in create_only_files:
        create_only_set.add(path)

    raw_items = module_dict.get('delete_files') or []
    # Ensure raw_items is a concrete iterable (list/tuple) for type checking
    raw_items_seq = raw_items if isinstance(raw_items, (list, tuple)) else [raw_items]
    _apply_raw_delete_items(
        delete_set,
        raw_items_seq,
        delete_files,
        provider_id,
        history,
    )


def create_providers(directories: list[str]) -> Providers:
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
    merged_context: dict[str, object] = {}
    merged_anchors: dict[str, str] = {}
    merged_file_mappings: dict[str, str] = {}
    create_only_set: set[Path] = set()
    delete_set: set[Path] = set()

    # provenance history: posix path -> list of Decision instances
    history: dict[str, list[Decision]] = {}
    for directory in directories:
        module_path = Path(directory) / 'repolish.py'
        module_dict = get_module(str(module_path))
        provider_id = Path(directory).as_posix()
        _process_provider_dict(
            module_dict,
            merged_context,
            merged_anchors,
            merged_file_mappings,
            create_only_set,
            delete_set,
            provider_id,
            history,
        )
    return Providers(
        context=merged_context,
        anchors=merged_anchors,
        delete_files=list(delete_set),
        file_mappings=merged_file_mappings,
        create_only_files=list(create_only_set),
        delete_history=history,
    )
