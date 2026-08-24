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

import shlex
from typing import TYPE_CHECKING

from repolish.insertions.models import (
    DEFAULT_COMMENT_STYLES,
    CommentStyle,
    InsertionBlock,
    ParseDiagnostic,
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

    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        msg = f'Invalid insertion marker arguments: {exc}'
        raise ValueError(msg) from exc

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
    file_path: str = '',
) -> InsertionBlock:
    """Create the insertion block state for an opening marker."""
    function, args = _split_function_args(payload)

    return InsertionBlock(
        tag=tag,
        function=function,
        args=args,
        start=match.start(),
        end=match.end(),
        body_start=match.end(),
        body_end=match.start(),
        comment_style=style,
        file_path=file_path,
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
        file_path=opener.file_path,
    )


def _process_marker(  # noqa: PLR0913 - helper function, only used in module
    style: CommentStyle,
    match: re.Match[str],
    open_stack: dict[str, InsertionBlock],
    diagnostics: list[ParseDiagnostic],
    text: str,
    file_path: str = '',
) -> InsertionBlock | None:
    """Process a single marker match and return a completed block if closing."""
    tag = match.group('tag')
    kind = match.group('kind')
    payload = match.group('body')

    if kind == 'on':
        _handle_open_marker(
            tag,
            payload,
            style,
            match,
            open_stack,
            diagnostics,
            file_path,
        )
        return None

    return _handle_close_marker(tag, match, open_stack, diagnostics, text)


def _handle_open_marker(  # noqa: PLR0913 - helper function, refactor later
    tag: str,
    payload: str | None,
    style: CommentStyle,
    match: re.Match[str],
    open_stack: dict[str, InsertionBlock],
    diagnostics: list[ParseDiagnostic],
    file_path: str = '',
) -> None:
    """Handle an opening marker, detecting duplicates and invalid syntax."""
    if tag in open_stack:
        diagnostics.append(
            ParseDiagnostic(
                message=f'Insertion tag {tag!r} is already open in this file.',
                position=match.start(),
            ),
        )
        return

    try:
        open_stack[tag] = _open_block(
            tag,
            payload,
            style=style,
            match=match,
            file_path=file_path,
        )
    except ValueError as exc:
        diagnostics.append(
            ParseDiagnostic(message=str(exc), position=match.start()),
        )


def _handle_close_marker(
    tag: str,
    match: re.Match[str],
    open_stack: dict[str, InsertionBlock],
    diagnostics: list[ParseDiagnostic],
    text: str,
) -> InsertionBlock | None:
    """Handle a closing marker, detecting mismatches."""
    if tag not in open_stack:
        diagnostics.append(
            ParseDiagnostic(
                message=f'Found closing insertion marker for tag {tag!r} without a matching opener.',
                position=match.start(),
            ),
        )
        return None

    opener = open_stack.pop(tag)
    return _close_block(opener, text=text, match=match)


def _finalize_unclosed_markers(
    open_stack: dict[str, InsertionBlock],
    diagnostics: list[ParseDiagnostic],
) -> None:
    """Record diagnostics for any markers that were never closed."""
    for tag, block in open_stack.items():
        diagnostics.append(
            ParseDiagnostic(
                message=f'Unclosed insertion marker for tag {tag!r}.',
                position=block.start,
            ),
        )


def parse_text(
    text: str,
    *,
    comment_styles: Iterable[CommentStyle | str] | None = DEFAULT_COMMENT_STYLES,
    file_path: str = '',
) -> ParsedInsertions:
    """Parse insertion markers from a string and return the structured blocks.

    Parse errors (unclosed markers, mismatched pairs, invalid syntax) are collected
    as diagnostics rather than raising, allowing callers to partially process files
    with malformed regions while still reporting what went wrong.

    Args:
        text: The file content to parse.
        comment_styles: The comment styles to recognize.
        file_path: The path of the file being parsed (stored in each InsertionBlock).
    """
    styles = _normalize_comment_styles(comment_styles)
    matches = _iter_marker_matches(text, styles)
    blocks: list[InsertionBlock] = []
    diagnostics: list[ParseDiagnostic] = []
    open_stack: dict[str, InsertionBlock] = {}

    for style, match in matches:
        block = _process_marker(
            style,
            match,
            open_stack,
            diagnostics,
            text,
            file_path,
        )
        if block is not None:
            blocks.append(block)

    _finalize_unclosed_markers(open_stack, diagnostics)

    return ParsedInsertions(text=text, blocks=blocks, diagnostics=diagnostics)
