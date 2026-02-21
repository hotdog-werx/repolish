from importlib.util import module_from_spec, spec_from_file_location


def get_module(module_path: str) -> dict[str, object]:
    """Dynamically import a module from a given path.

    Each invocation uses a unique name derived from the absolute path so
    subsequent loads of different providers do not accidentally share the
    same module object.  Prior behaviour used a fixed name which allowed one
    provider's globals (e.g. ``provider_migrated``) to leak into the next
    provider when running multiple directories in the same process.
    """
    # use the path itself as part of the module name; replace non-id characters
    # to keep the name valid.  hashing would also work but a sanitized path is
    # easier to debug in logs.
    mod_name = 'repolish_module_' + ''.join(c if c.isalnum() or c == '_' else '_' for c in module_path)
    spec = spec_from_file_location(mod_name, module_path)
    if not spec or not spec.loader:  # pragma: no cover
        msg = f'Cannot load module from path: {module_path}'
        raise ImportError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.__dict__
