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


def collect_contexts(module_cache: list[tuple[str, dict]]) -> dict[str, Any]:
    """Phase 1: collect and merge contexts from providers.

    Returns the merged context dict.
    """
    merged: dict[str, Any] = {}
    for _provider_id, module_dict in module_cache:
        _collect_context_from_module(module_dict, merged)
    return merged
