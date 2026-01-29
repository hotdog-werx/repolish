from importlib.util import module_from_spec, spec_from_file_location


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
