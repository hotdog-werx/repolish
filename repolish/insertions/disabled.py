"""Disabled insertion block detection and handling.

Insertion blocks can be disabled via renderer attributes:
- `__repolish_disabled_tags__` - frozenset of tags to disable
- `__repolish_disabled_functions__` - frozenset of functions to disable

This module provides canonical functions for detecting and collecting
disabled blocks, keeping the policy logic in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from repolish.insertions.models import InsertionBlock


@dataclass(frozen=True)
class DisabledInsertionEntry:
    """One insertion block that was intentionally disabled by overrides.

    Attributes:
        tag: The insertion block's tag name
        function: The function name from the block
        message: Human-readable reason for the disable
    """

    tag: str
    function: str
    message: str


def resolve_renderer_for_function(
    registry: Mapping[str, object],
    function_name: str,
) -> Callable | None:
    """Resolve a renderer the same way insertion writing resolves function lookups.

    Args:
        registry: The function registry (keyed by function name)
        function_name: The function name to look up (may be qualified)

    Returns:
        The renderer callable or None if not found
    """
    renderer = registry.get(function_name)
    if renderer is None and ':' in function_name:
        renderer = registry.get(function_name.rsplit(':', 1)[1])
    return cast('Callable | None', renderer)


def disabled_reason_for_block(
    block: InsertionBlock,
    registry: Mapping[str, object],
) -> str | None:
    """Return a human-readable disable reason for one block, when configured.

    Checks renderer attributes for disable flags:
    - `__repolish_disabled_tags__` - tag-based overrides
    - `__repolish_disabled_functions__` - function-based overrides

    Args:
        block: The insertion block to check
        registry: The function registry

    Returns:
        Disable reason message if disabled, None otherwise
    """
    renderer = resolve_renderer_for_function(registry, block.function)
    if renderer is None:
        return None

    disabled_tags = getattr(renderer, '__repolish_disabled_tags__', frozenset())
    if block.tag in disabled_tags:
        return f'Insertion block disabled by tag override: tag={block.tag!r}, function={block.function!r}.'

    disabled_functions = getattr(
        renderer,
        '__repolish_disabled_functions__',
        frozenset(),
    )
    if disabled_functions:
        return f'Insertion block disabled by function override: tag={block.tag!r}, function={block.function!r}.'

    return None


def collect_disabled_entries(
    blocks: Iterable[InsertionBlock],
    registry: dict,
) -> list[DisabledInsertionEntry]:
    """Collect disabled insertion metadata for summary/report output.

    Args:
        blocks: All insertion blocks to check
        registry: The function registry

    Returns:
        List of DisabledInsertionEntry for all disabled blocks
    """
    entries: list[DisabledInsertionEntry] = []
    for block in blocks:
        reason = disabled_reason_for_block(block, registry)
        if reason is not None:
            entries.append(
                DisabledInsertionEntry(
                    tag=block.tag,
                    function=block.function,
                    message=reason,
                ),
            )
    return entries
