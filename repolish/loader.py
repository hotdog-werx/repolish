from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from hotlog import get_logger

logger = get_logger(__name__)


def get_module(module_path: str) -> dict[str, Any]:
    """Dynamically import a module from a given path."""
    spec = spec_from_file_location('repolish_module', module_path)
    if not spec or not spec.loader:  # pragma: no cover
        # We shouldn't reach this point in tests due to other validations
        msg = f'Cannot load module from path: {module_path}'
        raise ImportError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.__dict__


def extract_context_from_module(
    module_path: str,
) -> dict[str, Any] | None:
    """Extract the context from a module by executing its create_context function.

    Args:
        module_path: Path to the module file.

    Returns:
        A dictionary representing the context, or None if not found or invalid.
    """
    module_dict = get_module(module_path)
    create_context_func = module_dict.get('create_context')
    if callable(create_context_func):
        context = create_context_func()
        if isinstance(context, dict):
            return context
    logger.warning('create_context_not_found', module=module_path)
    return None


def create_context(directories: list[str]) -> dict[str, Any]:
    """Create a context from the template directories.

    Args:
        directories: List of paths to template directories.

    Returns:
        Merged context dictionary from all directories.
    """
    context: dict[str, Any] = {}
    for directory in directories:
        module_path = Path(directory) / 'repolish.py'
        dir_context = extract_context_from_module(str(module_path))
        if dir_context:
            context.update(dir_context)
    return context
