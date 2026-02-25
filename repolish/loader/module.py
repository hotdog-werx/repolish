import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _guess_import_name(module_path: str) -> str | None:
    """Infer a dotted module name for a provider file, if possible.

    Iterate ``sys.path`` entries looking for one that contains the given
    file.  When the file lives inside a package hierarchy we build the
    dotted name from the relative path and ensure each parent directory is a
    proper package (has ``__init__.py``).  The first valid candidate is
    returned; otherwise ``None`` indicates the path isn't importable via a
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
        parents = (base / p for p in parts[:-1])
        if all((parent / '__init__.py').exists() for parent in parents):
            return '.'.join(parts)
    return None


def get_module(module_path: str) -> dict[str, object]:
    """Dynamically import a module from a given path.

    The loader prefers re-using an existing module object when one has
    already been imported from the same file path.  This avoids the
    classic "class equals itself but with different identity" problem that
    occurs when the same source file is executed multiple times under
    different module names.  In particular, consumers often import a
    provider via its canonical package name (e.g. ``package.repolish``) and
    then the loader would later re-execute the file as
    ``repolish_module_…``; the two resulting classes were incompatible. By
    checking ``sys.modules`` we detect such duplicates and simply return the
    already-loaded module's globals.

    When no existing module is found we fall back to the previous behaviour
    of loading the file under a sanitized name derived from its path.  If
    the module appears to belong to an importable package we also register
    it under that inferred name so later ``importlib.import_module`` calls
    will resolve to the same object instead of reloading the file again.
    """
    # If the module has been imported earlier (under any name) reuse it.
    # We match on absolute file path because ``__file__`` may be either
    # absolute or relative depending on how the import happened.
    abs_path = Path(module_path).resolve()
    for mod in list(sys.modules.values()):
        file_path = getattr(mod, '__file__', None)
        if file_path and Path(file_path).resolve() == abs_path:
            # found existing module - use its namespace directly
            return mod.__dict__

    # Otherwise dynamically create a new module with a unique but stable
    # name derived from the path.  This is identical to the previous
    # implementation.
    mod_name = 'repolish_module_' + ''.join(c if c.isalnum() or c == '_' else '_' for c in module_path)
    spec = spec_from_file_location(mod_name, module_path)
    if not spec or not spec.loader:  # pragma: no cover
        msg = f'Cannot load module from path: {module_path}'
        raise ImportError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    # Attempt to register under a canonical import name when possible so
    # later ``import_module`` calls will hit the same object.  This is a
    # no-op if the name cannot be inferred or is already present.
    import_name = _guess_import_name(module_path)
    if import_name and import_name not in sys.modules:
        sys.modules[import_name] = module
    return module.__dict__
