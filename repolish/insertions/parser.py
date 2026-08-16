"""Parser for developer-defined insertion blocks in project files.

The parser recognizes blocks of the form:

    <!-- repolish:on:tag function arg1 arg2 -->
    ... replacement body ...
    <!-- repolish:off:tag -->

It also supports line-based comment styles such as:

    # repolish:on:tag function arg1 arg2
    ...
    # repolish:off:tag

    // repolish:on:tag function arg1 arg2
    ...
    // repolish:off:tag

It returns structured metadata for each block, including the tag name,
function name, args, and the content between the markers. This is intentionally
kept small and syntax-focused so the resolver and writer can be implemented as
separate steps.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from repolish.insertions.models import (
    DEFAULT_COMMENT_STYLES,
    CommentStyle,
    InsertionBlock,
    ParsedInsertions,
)

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable


def _normalize_comment_styles(
    comment_styles: Iterable[CommentStyle | str] | None,
) -> tuple[CommentStyle, ...]:
    """Normalize the allowed comment styles into a tuple of enums."""
    if comment_styles is None:
        return DEFAULT_COMMENT_STYLES

    result: list[CommentStyle] = []
    for style in comment_styles:
        if not style:
            continue

        value = style.lower() if isinstance(style, str) else style.value.lower()
        try:
            result.append(CommentStyle(value))
        except ValueError:
            result.append(CommentStyle.HTML)

    return tuple(result) if result else DEFAULT_COMMENT_STYLES


def _split_function_args(raw: str | None) -> tuple[str, tuple[str, ...]]:
    """Return (function-name, args) from the marker payload."""
    if raw is None:
        return '', ()

    parts = raw.split()
    if not parts:
        return '', ()
    return parts[0], tuple(parts[1:])


def _iter_marker_matches(
    text: str,
    comment_styles: Iterable[CommentStyle],
) -> list[tuple[CommentStyle, re.Match[str]]]:
    """Collect all marker matches across the requested comment styles."""
    matches: list[tuple[CommentStyle, re.Match[str]]] = []
    for style in comment_styles:
        matches.extend((style, match) for match in style.regex.finditer(text))
    matches.sort(key=lambda item: item[1].start())
    return matches


def _open_block(
    tag: str,
    payload: str | None,
    *,
    style: CommentStyle,
    match: re.Match[str],
) -> InsertionBlock:
    """Create the insertion block state for an opening marker."""
    function, args = _split_function_args(payload)
    if not function:
        msg = f'Insertion marker for tag {tag!r} is missing a function name.'
        raise ValueError(msg)

    return InsertionBlock(
        tag=tag,
        function=function,
        args=args,
        start=match.start(),
        end=match.end(),
        body_start=match.end(),
        body_end=match.start(),
        comment_style=style,
    )


def _close_block(
    opener: InsertionBlock,
    text: str,
    *,
    match: re.Match[str],
) -> InsertionBlock:
    """Close an insertion block and capture the content between markers."""
    body_start = opener.end
    body_end = match.start()
    return InsertionBlock(
        tag=opener.tag,
        function=opener.function,
        args=opener.args,
        body=text[body_start:body_end],
        start=opener.start,
        end=match.end(),
        body_start=body_start,
        body_end=body_end,
        comment_style=opener.comment_style,
    )


def parse_text(
    text: str,
    *,
    comment_styles: Iterable[CommentStyle | str] | None = DEFAULT_COMMENT_STYLES,
) -> ParsedInsertions:
    """Parse insertion markers from a string and return the structured blocks."""
    styles = _normalize_comment_styles(comment_styles)
    matches = _iter_marker_matches(text, styles)
    blocks: list[InsertionBlock] = []
    open_stack: dict[str, InsertionBlock] = {}

    for style, match in matches:
        tag = match.group('tag')
        kind = match.group('kind')
        payload = match.group('body')

        if kind == 'on':
            if tag in open_stack:
                msg = f'Insertion tag {tag!r} is already open in this file.'
                raise ValueError(msg)
            open_stack[tag] = _open_block(
                tag,
                payload,
                style=style,
                match=match,
            )
            continue

        if tag not in open_stack:
            msg = f'Found closing insertion marker for tag {tag!r} without a matching opener.'
            raise ValueError(msg)

        blocks.append(_close_block(open_stack.pop(tag), text, match=match))

    if open_stack:
        dangling = ', '.join(sorted(open_stack))
        msg = f'Unclosed insertion markers remain: {dangling}'
        raise ValueError(msg)

    return ParsedInsertions(text=text, blocks=blocks)


def parse_file(
    path: str | Path,
    *,
    comment_styles: Iterable[CommentStyle | str] | None = DEFAULT_COMMENT_STYLES,
) -> ParsedInsertions:
    """Parse insertion markers from a file path."""
    file_path = Path(path)
    return parse_text(
        file_path.read_text(encoding='utf-8'),
        comment_styles=comment_styles,
    )
