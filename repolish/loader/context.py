from typing import Any, TypeVar

from repolish.loader._log import logger

T = TypeVar('T')


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
