import inspect
from collections.abc import Callable, Iterable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path, PurePosixPath
from typing import Any

from hotlog import get_logger

from .types import Accumulators, Action, Decision, Providers

logger = get_logger(__name__)


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


def _call_factory_with_context(
    factory: Callable[..., object],
    context: dict[str, object],
) -> object:
    """Call a provider factory allowing 0 or 1 positional argument.

    Backwards-compatible: if the factory accepts no parameters it will be
    invoked without arguments. If it accepts one parameter the merged
    context dict is passed. Any other signature is rejected.
    """
    sig = inspect.signature(factory)
    params = len(sig.parameters)
    if params == 0:
        return factory()
    if params == 1:
        return factory(context)
    msg = f'Provider factory must accept 0 or 1 args, got {params}'
    raise TypeError(msg)


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


def _collect_context_from_module(
    module_dict: dict[str, object],
    merged: dict[str, Any],
) -> None:
    """Helper: collect and merge context from a single module dict into merged."""
    create_ctx = module_dict.get('create_context')
    if callable(create_ctx):
        val = _call_factory_with_context(create_ctx, merged)
        if val is not None and not isinstance(val, dict):
            msg = 'create_context() must return a dict'
            raise TypeError(msg)
        if isinstance(val, dict):
            merged.update(val)
        return

    ctx_var = module_dict.get('context')
    if isinstance(ctx_var, dict):
        merged.update(ctx_var)


def _collect_contexts(module_cache: list[tuple[str, dict]]) -> dict[str, Any]:
    """Phase 1: collect and merge contexts from providers.

    Returns the merged context dict.
    """
    merged: dict[str, Any] = {}
    for _provider_id, module_dict in module_cache:
        _collect_context_from_module(module_dict, merged)
    return merged


def _process_phase_two(
    module_cache: list[tuple[str, dict]],
    merged_context: dict[str, Any],
    accum: Accumulators,
) -> None:
    """Phase 2: process anchors, file mappings, delete/create-only files.

    This mutates the provided accumulators in-place.
    """
    for provider_id, module_dict in module_cache:
        _process_anchors(module_dict, merged_context, accum.merged_anchors)
        _process_file_mappings(
            module_dict,
            merged_context,
            accum.merged_file_mappings,
        )
        fallback_paths = _process_delete_files(
            module_dict,
            merged_context,
            accum.delete_set,
        )
        _process_create_only_files(
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


def _process_anchors(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    merged_anchors: dict[str, str],
) -> None:
    anchors_fact = module_dict.get('create_anchors') or module_dict.get(
        'anchors',
    )
    if callable(anchors_fact):
        val = _call_factory_with_context(anchors_fact, merged_context)
        if val is None:
            return
        if not isinstance(val, dict):
            msg = 'create_anchors() must return a dict'
            raise TypeError(msg)
        merged_anchors.update(val)
    elif isinstance(anchors_fact, dict):
        merged_anchors.update(anchors_fact)


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


def _process_delete_files(
    module_dict: dict[str, object],
    merged_context: dict[str, object],
    delete_set: set[Path],
) -> list[Path]:
    df_fact = module_dict.get('create_delete_files')
    df: list | tuple | None = None
    fallback_paths: list[Path] = []
    if callable(df_fact):
        val = _call_factory_with_context(df_fact, merged_context)
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


def _is_suspicious_create_only_function(name: str) -> bool:
    """Check if a function name looks like a typo of create_create_only_files."""
    return 'create_only' in name or 'createonly' in name


def _is_suspicious_variable(name: str, valid_variables: set[str]) -> bool:
    """Check if a variable name looks like a typo of a provider variable."""
    if name in ('create_only_file', 'createonly_files', 'create_files'):
        return True
    if name.endswith('_files') and name not in valid_variables:
        return not name.startswith('create_')
    if name.endswith('_mappings') and name not in valid_variables:
        return not name.startswith('create_')
    return False


def _warn_suspicious_function(name: str, valid_functions: set[str]) -> None:
    """Emit warning for suspicious function name."""
    if _is_suspicious_create_only_function(name):
        logger.warning(
            'suspicious_provider_function',
            function_name=name,
            suggestion='Did you mean create_create_only_files?',
        )
    else:
        logger.warning(
            'unknown_provider_function',
            function_name=name,
            valid_functions=sorted(valid_functions),
        )


def _validate_provider_module(module_dict: dict[str, object]) -> None:
    """Validate provider module for common typos and emit warnings.

    Checks for functions that look like provider functions but have typos,
    such as 'create_creat_only_files' or other misspellings.
    """
    # Known valid function names
    valid_functions = {
        'create_context',
        'create_delete_files',
        'create_file_mappings',
        'create_create_only_files',
        'create_anchors',
    }

    # Known valid variable names
    valid_variables = {
        'context',
        'delete_files',
        'file_mappings',
        'create_only_files',
        'anchors',
    }

    # Check for suspicious names that might be typos
    for name, value in module_dict.items():
        # Skip private/dunder names
        if name.startswith('_'):
            continue

        is_callable = callable(value)

        # Check for functions that start with 'create_' but aren't valid
        if is_callable and name.startswith('create_') and name not in valid_functions:
            _warn_suspicious_function(name, valid_functions)

        # Check for variables that look like provider variables but have typos
        elif not is_callable and _is_suspicious_variable(name, valid_variables):
            logger.warning(
                'suspicious_provider_variable',
                variable_name=name,
                valid_variables=sorted(valid_variables),
            )


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
    # Two-phase load: first collect contexts (allowing providers to see
    # a base context if provided), then call other factories with the
    # fully merged context so factories can make decisions based on it.
    merged_context: dict[str, object] = {}
    merged_anchors: dict[str, str] = {}
    merged_file_mappings: dict[str, str] = {}
    create_only_set: set[Path] = set()
    delete_set: set[Path] = set()

    # provenance history: posix path -> list of Decision instances
    history: dict[str, list[Decision]] = {}

    module_cache = _load_module_cache(directories)
    merged_context = _collect_contexts(module_cache)
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
