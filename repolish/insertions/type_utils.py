"""Type annotation inspection utilities for insertion functions.

Insertion functions can request context injection via type annotations:

```python
def my_insertion(block: InsertionBlock) -> str:
    ...

def my_insertion(*, ctx: BlockContext) -> str:
    ...
```

These helpers detect when a function's type annotations refer to
`InsertionBlock` or `BlockContext`, including:
- Direct type references (`InsertionBlock`)
- String annotations (`'InsertionBlock'`, `'repolish.insertions.InsertionBlock'`)
- Forward references (`from __future__ import annotations`)

This enables automatic context injection without requiring explicit
positional parameters.
"""

from __future__ import annotations

from types import UnionType
from typing import Union, get_args, get_origin

from repolish.insertions.models import BlockContext, InsertionBlock


def is_insertion_block_annotation(annotation: object) -> bool:
    """Check if a type annotation refers to `InsertionBlock`.

    Handles:
    - Direct type: `InsertionBlock`
    - String annotation: `'InsertionBlock'` or `'repolish.insertions.InsertionBlock'`
    - Forward reference: `from __future__ import annotations` with `InsertionBlock`
    - Optional: `InsertionBlock | None`

    Args:
        annotation: A type annotation from a function parameter

    Returns:
        True if the annotation refers to InsertionBlock (or Optional[InsertionBlock])
    """
    # Handle Optional[T] / T | None
    if _is_optional(annotation):
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return is_insertion_block_annotation(non_none[0])
        return False

    # Direct type reference
    if annotation is InsertionBlock:
        return True

    # String annotation (e.g., 'InsertionBlock' or 'repolish.insertions.InsertionBlock')
    if isinstance(annotation, str):
        return annotation == 'InsertionBlock' or annotation.endswith(
            '.InsertionBlock',
        )

    # Forward reference (from __future__ import annotations)
    forward_arg = getattr(annotation, '__forward_arg__', None)
    if isinstance(forward_arg, str):
        return forward_arg == 'InsertionBlock' or forward_arg.endswith(
            '.InsertionBlock',
        )

    return False


def is_block_context_annotation(annotation: object) -> bool:
    """Check if a type annotation refers to `BlockContext`.

    Handles:
    - Direct type: `BlockContext`
    - String annotation: `'BlockContext'` or `'repolish.insertions.BlockContext'`
    - Optional: `BlockContext | None`

    Note: BlockContext is not expected to be used with forward references
    in typical insertion function signatures.

    Args:
        annotation: A type annotation from a function parameter

    Returns:
        True if the annotation refers to BlockContext (or Optional[BlockContext])
    """
    # Handle Optional[T] / T | None
    if _is_optional(annotation):
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return is_block_context_annotation(non_none[0])
        return False

    # Direct type reference
    if annotation is BlockContext:
        return True

    # String annotation
    if isinstance(annotation, str):
        return annotation == 'BlockContext' or annotation.endswith(
            '.BlockContext',
        )

    return False


def _is_optional(annotation: object) -> bool:
    """Check if an annotation is Optional[T] (i.e., T | None)."""
    origin = get_origin(annotation)
    if origin in {UnionType, Union}:
        return any(arg is type(None) for arg in get_args(annotation))
    return False
