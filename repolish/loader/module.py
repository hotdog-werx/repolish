import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _guess_import_name(module_path: str) -> str | None:
    """Infer a dotted module name for a provider file, if possible.

    Iterate `sys.path` entries looking for one that contains the given
    file.  When the file lives inside a package hierarchy we build the
    dotted name from the relative path and ensure each parent directory is a
    proper package (has `__init__.py`).  The first valid candidate is
    returned; otherwise `None` indicates the path isn't importable via a
    normal package name.
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
        # once we know the file lives below a sys.path entry we consider the
        # dotted name to be the joined relative components.  this is the only
        # information the loader actually needs; verifying the existence of
        # `__init__.py` files proved fragile in practice and could yield
        # incorrect results when the package root wasn't chosen as expected.
        return '.'.join(parts)
    return None


def _try_imported_module(abs_path: Path, name: str) -> dict[str, object] | None:
    """Return namespace for `name` if it already points at `abs_path`.

    This helper encapsulates the import-attempt logic so `get_module` can
    remain within ruff's complexity budget.  `None` means either the name
    couldn't be imported or it resolved to a different file.
    """
    try:
        imported = __import__(name, fromlist=['*'])
    except ImportError:
        return None
    file_attr = getattr(imported, '__file__', None)
    if file_attr is None:
        return None
    if Path(file_attr).resolve() == abs_path:
        return imported.__dict__
    return None


def _load_module_from_path(
    module_path: str,
    import_name: str | None,
) -> dict[str, object]:
    """Load a module by executing its file and optionally register it.

    This is the "fallback" path used when the provider cannot be imported by
    a guessed name or has not yet been executed.  The module will be created
    under a synthetic name based on the file path to avoid conflicts.
    If `import_name` is provided and not already present in `sys.modules`
    the newly loaded module will be inserted there as well so future
    `import_module` calls resolve to the same object.
    """
    mod_name = 'repolish_module_' + ''.join(c if c.isalnum() or c == '_' else '_' for c in module_path)
    spec = spec_from_file_location(mod_name, module_path)
    if not spec or not spec.loader:  # pragma: no cover
        msg = f'Cannot load module from path: {module_path}'
        raise ImportError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    if import_name and import_name not in sys.modules:
        sys.modules[import_name] = module
    return module.__dict__


def get_module(module_path: str) -> dict[str, object]:
    """Dynamically import a module from a given path.

    The loader prefers re-using an existing module object when one has
    already been imported from the same file path.  This avoids the
    classic "class equals itself but with different identity" problem that
    occurs when the same source file is executed multiple times under
    different module names.  In particular, consumers often import a
    provider via its canonical package name (e.g. `package.repolish`) and
    then the loader would later re-execute the file as
    `repolish_module_…`; the two resulting classes were incompatible. By
    checking `sys.modules` we detect such duplicates and simply return the
    already-loaded module's globals.

    When no existing module is found we fall back to the previous behaviour
    of loading the file under a sanitized name derived from its path.  If
    the module appears to belong to an importable package we also register
    it under that inferred name so later `importlib.import_module` calls
    will resolve to the same object instead of reloading the file again.
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
