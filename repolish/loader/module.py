import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


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
    of loading the file under a sanitized name derived from its path.
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
    return module.__dict__
