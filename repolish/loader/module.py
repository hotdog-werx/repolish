import sys
from importlib.util import module_from_spec, spec_from_file_location
from inspect import isclass
from pathlib import Path

from repolish.loader.models import Provider as _ProviderBase


def _guess_import_name(module_path: str) -> str | None:
    """Return an importable dotted module name for the given file path.

    Search entries in `sys.path` for a base that contains `module_path`.
    When the file resides under a `sys.path` entry, the dotted module name is
    constructed from the relative path by removing the `.py` suffix and
    joining path components with dots (for example,
    `/.../pkg/sub/module.py` -> `pkg.sub.module`).

    Args:
        module_path: Path to a Python source file.

    Returns:
        A dotted module name if the file appears under any `sys.path` entry;
        otherwise `None`. This is a best-effort guess used to prefer
        importing a module by name instead of executing its file directly.

    Notes:
        The function does not verify package metadata (for example,
        `__init__.py` presence). Callers should treat the result as a
        suggested import name, not a guarantee of successful import.
    """
    path = Path(module_path).resolve()
    if path.suffix != '.py':
        return None

    for entry in sys.path:
        base = Path(entry).resolve()
        try:
            rel = path.relative_to(base)
        except ValueError:  # not under this sys.path entry
            continue

        parts = rel.with_suffix('').parts
        # File is under a sys.path entry — use the relative parts as the
        # dotted import name (e.g. pkg.sub.module).
        return '.'.join(parts)
    return None


def _try_imported_module(abs_path: Path, name: str) -> dict[str, object] | None:
    """Return the imported module namespace if `name` resolves to `abs_path`.

    Attempt to import the dotted module name `name`. If the import succeeds
    and the imported module's `__file__` resolved path equals `abs_path`,
    return the module's globals dictionary (the same object as
    `module.__dict__`). If the name cannot be imported or it resolves to
    a different file, return `None`.

    Args:
        abs_path: The expected absolute path to the module source file.
        name: Dotted import name to attempt (for example, `package.module`).

    Returns:
        The module globals mapping when the imported module originates from
        `abs_path`, otherwise `None`.

    Notes:
        Importing a module executes its top-level code and may have
        side-effects; this function is a best-effort check used to avoid
        re-executing the same source file under a different module name.
    """
    try:
        imported = __import__(name, fromlist=['*'])
    except ImportError:
        return None
    file_attr = getattr(imported, '__file__', None)
    return imported.__dict__ if file_attr and Path(file_attr).resolve() == abs_path else None


def _load_module_from_path(
    module_path: str,
    import_name: str | None,
) -> dict[str, object]:
    """Execute a Python file as a module and return its globals mapping.

    This function loads the source at `module_path` under a synthetic
    module name (derived from the path) and executes it. If `import_name`
    is provided and not already present in `sys.modules`, the loaded module
    is also inserted under `import_name` so future imports resolve to the
    same module object.

    Args:
        module_path: Path to the Python file to execute.
        import_name: Optional dotted name to register the loaded module under.

    Returns:
        The module globals mapping (equivalent to `module.__dict__`).

    Raises:
        ImportError: If the module cannot be loaded from the given path.

    Notes:
        Executing a module runs its top-level code; callers should be aware
        of potential side-effects. This is intended as a fallback for
        uninstalled or temporary provider files.
    """
    safe_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in module_path)
    mod_name = f'repolish_module_{safe_name}'
    spec = spec_from_file_location(mod_name, module_path)
    if not spec or not spec.loader:
        msg = f'Cannot load module from path: {module_path}'
        raise ImportError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    if import_name and import_name not in sys.modules:
        sys.modules[import_name] = module
    return module.__dict__


def get_module(module_path: str) -> dict[str, object]:
    """Load a module from `module_path` and return its globals mapping.

    Prefer an already-loaded module that originates from the same file
    path, or import the module by a guessed dotted name. If neither
    succeeds, execute the source file under a synthetic module name and
    return the resulting module globals.

    Args:
        module_path: Path to the Python source file to load.

    Returns:
        The module globals mapping for the module loaded from `module_path`.

    Notes:
        Executing a file runs its top-level code; a synthetic module name
        is used for fallback loading to avoid import name conflicts.
    """
    abs_path = Path(module_path).resolve()

    # existing module by path
    for mod in list(sys.modules.values()):
        file_path = getattr(mod, '__file__', None)
        if file_path and Path(file_path).resolve() == abs_path:
            return mod.__dict__

    import_name = _guess_import_name(module_path)
    if import_name:
        result = _try_imported_module(abs_path, import_name)
        if result is not None:
            return result

    # fallback to spec-based loading (handles uninstalled or temporary
    # providers).  `_load_module_from_path` encapsulates the mechanics
    # and also registers the module under `import_name` if provided.
    return _load_module_from_path(module_path, import_name)


def _find_provider_class(
    module_dict: dict[str, object],
) -> type[_ProviderBase] | None:
    """Return the single Provider subclass exported in `module_dict`.

    If the module exports no subclasses `None` is returned.  The loader
    historically picked the *first* subclass it encountered, but this hid
    user errors where a file accidentally defined multiple providers (e.g.
    importing another provider class into the same module).  The caller
    (`_maybe_instantiate_provider`) expects at most one class; if there are
    multiple we raise a `RuntimeError` so the problem is detected right
    away.

    Keeping the detection logic isolated makes the behaviour easy to test
    and keeps the surrounding code simple.
    """
    providers: list[type[_ProviderBase]] = [
        val
        for val in module_dict.values()
        if isclass(val) and issubclass(val, _ProviderBase) and val is not _ProviderBase
    ]

    # If the module defines ``__all__`` we treat it as the explicit export
    # list.  this lets authors import other provider classes for utility
    # purposes while still exporting a single implementation.  the list may
    # contain arbitrary names; we only consider entries that match provider
    # class names.  if a single provider appears in ``__all__`` we return
    # that class even if others are present at module level.  the module may
    # still define no public providers, in which case we behave as though
    # no subclass were exported.
    all_list = module_dict.get('__all__')
    if isinstance(all_list, (list, tuple)) and all_list:
        # filter the providers down to those listed explicitly
        filtered = [cls for cls in providers if cls.__name__ in all_list]
        if len(filtered) == 1:
            return filtered[0]
        if len(filtered) > 1:
            names = ', '.join(cls.__name__ for cls in filtered)
            msg = f'__all__ exports multiple Provider subclasses ({names}); only one class may be exported per file'
            raise RuntimeError(msg)
        # if ``__all__`` is present but doesn't mention any providers we
        # continue with the normal logic below; the user has effectively
        # hidden all classes from export.

    if not providers:
        return None
    if len(providers) > 1:
        names = ', '.join(cls.__name__ for cls in providers)
        msg = (
            f'provider module exports multiple Provider subclasses ({names}); '
            'only one class may be defined per file; if you meant to expose a '
            'single implementation please add that class name to ``__all__``'
        )
        raise RuntimeError(msg)
    return providers[0]


def _maybe_instantiate_provider(
    module_dict: dict[str, object],
) -> None:
    """Instantiate a Provider subclass and store the instance in `module_dict`.

    The instance is stored under ``_repolish_provider_instance`` for later
    retrieval by ``_collect_provider_contributions`` and diagnostics.  Raises
    ``RuntimeError`` if the module does not export exactly one subclass.
    """
    cls = _find_provider_class(module_dict)
    if not cls:
        msg = 'provider module does not export a Provider subclass'
        raise RuntimeError(msg)

    inst = cls()
    inst.templates_root = Path(str(module_dict.get('__file__', '.'))).resolve().parent
    module_dict['_repolish_provider_instance'] = inst


def _load_module_cache(directories: list[str]) -> list[tuple[str, dict]]:
    """Load provider modules and validate them.

    Returns a list of (provider_id, module_dict) tuples.
    """
    cache: list[tuple[str, dict]] = []
    for directory in directories:
        module_path = Path(directory) / 'repolish.py'
        module_dict = get_module(str(module_path))
        provider_id = Path(directory).as_posix()

        # Detect and instantiate class-based providers
        _maybe_instantiate_provider(module_dict)

        cache.append((provider_id, module_dict))
    return cache
