import inspect
from collections.abc import Callable
from typing import Any

from ._log import logger
from .module import get_module


def call_factory_with_context(
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


def extract_from_module_dict(
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
    ctx = extract_from_module_dict(
        module_dict,
        'create_context',
        expected_type=dict,
    )
    if isinstance(ctx, dict):
        return ctx
    # Also accept a module-level `context` variable for compatibility
    ctx2 = extract_from_module_dict(
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


def _collect_context_from_module(
    module_dict: dict[str, object],
    merged: dict[str, Any],
) -> None:
    """Helper: collect and merge context from a single module dict into merged."""
    create_ctx = module_dict.get('create_context')
    if callable(create_ctx):
        val = call_factory_with_context(create_ctx, merged)
        if val is not None and not isinstance(val, dict):
            msg = 'create_context() must return a dict'
            raise TypeError(msg)
        if isinstance(val, dict):
            merged.update(val)
        return

    ctx_var = module_dict.get('context')
    if isinstance(ctx_var, dict):
        merged.update(ctx_var)


def collect_contexts(
    module_cache: list[tuple[str, dict]],
    initial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 1: collect and merge contexts from providers.

    If `initial` is provided it will be used as the starting merged context
    so providers see those values when their `create_context()` factories
    are invoked. The function returns the merged dict (providers may add or
    override keys).
    """
    merged: dict[str, Any] = dict(initial or {})
    for _provider_id, module_dict in module_cache:
        _collect_context_from_module(module_dict, merged)
    return merged


def apply_context_overrides(
    context: dict[str, Any],
    overrides: dict[str, Any],
) -> None:
    """Apply context overrides using dot-notation paths.

    Supports both flat dot-notation keys and nested dictionary structures.
    Nested structures are flattened to dot-notation before application.

    Modifies the context in-place. Logs warnings for invalid paths.
    """
    flattened = _flatten_override_dict(overrides)
    for path, value in flattened.items():
        _apply_override(context, path.split('.'), value)


def _flatten_override_dict(overrides: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested override dictionaries to dot-notation keys."""
    flattened = {}

    for key, value in overrides.items():
        if isinstance(value, dict):
            # Nested dict that needs flattening - use the key as prefix
            _flatten_nested_dict(value, key, flattened)
        else:
            # Simple key-value pair
            flattened[key] = value

    return flattened


def _flatten_nested_dict(
    nested: dict[str, Any],
    prefix: str,
    flattened: dict[str, Any],
) -> None:
    """Flatten a nested dictionary into the flattened dict."""
    for key, value in nested.items():
        full_key = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            _flatten_nested_dict(value, full_key, flattened)
        else:
            flattened[full_key] = value


def _apply_override(
    obj: object,
    path_parts: list[str],
    value: object,
) -> None:
    """Recursively apply an override at the given path."""
    if not path_parts:
        return  # Should not happen

    key = path_parts[0]
    remaining = path_parts[1:]

    if isinstance(obj, dict):
        _apply_override_to_dict(obj, key, remaining, value)
    elif isinstance(obj, list):
        _apply_override_to_list(obj, key, remaining, value)
    else:
        logger.warning(
            'context_override_cannot_navigate',
            key=key,
            current_type=type(obj).__name__,
        )


def _apply_override_to_dict(
    obj: dict,
    key: str,
    remaining: list[str],
    value: object,
) -> None:
    """Apply override to a dictionary."""
    if not remaining:
        obj[key] = value
        return
    if key not in obj:
        # Create intermediate dictionary for nested path navigation
        obj[key] = {}
    _apply_override(obj[key], remaining, value)


def _apply_override_to_list(
    obj: list,
    key: str,
    remaining: list[str],
    value: object,
) -> None:
    """Apply override to a list."""
    try:
        index = int(key)
        if 0 <= index < len(obj):
            if not remaining:
                obj[index] = value
                return
            _apply_override(obj[index], remaining, value)
        else:
            logger.warning(
                'context_override_index_out_of_range',
                index=index,
                list_length=len(obj),
            )
    except ValueError:
        logger.warning(
            'context_override_invalid_index',
            key=key,
            expected_integer=True,
        )
