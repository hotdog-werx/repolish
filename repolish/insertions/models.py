"""Models for insertion markers and parsed file content."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class CommentStyle(StrEnum):
    """Supported comment syntaxes for insertion markers."""

    HTML = 'html'
    HASH = 'hash'
    JS = 'js'
    BLOCK = 'block'

    @property
    def pattern(self) -> str:
        """Return a regex pattern for this comment style."""
        if self is CommentStyle.HTML:
            return (
                r'<!--\s*repolish:(?P<kind>on|off):(?P<tag>[^\s>]+)'
                r'(?:\s+(?P<body>[^\n\r]*))?\s*-->'
            )
        if self is CommentStyle.HASH:
            return (
                r'(?m)^(?:\s*#\s*repolish:(?P<kind>on|off):(?P<tag>[^\s]+)'
                r'(?:\s+(?P<body>[^\n\r]*))?\s*)$'
            )
        if self is CommentStyle.JS:
            return (
                r'(?m)^(?:\s*//\s*repolish:(?P<kind>on|off):(?P<tag>[^\s]+)'
                r'(?:\s+(?P<body>[^\n\r]*))?\s*)$'
            )
        if self is CommentStyle.BLOCK:
            return (
                r'(?m)^(?:\s*/\*\s*repolish:(?P<kind>on|off):(?P<tag>[^\s]+)'
                r'(?:\s+(?P<body>[^\n\r]*))?\s*\*/\s*)$'
            )
        return CommentStyle.HTML.pattern  # pragma: no cover -- should not reach this

    @property
    def regex(self) -> re.Pattern[str]:
        """Return a compiled regex for this comment style."""
        return re.compile(self.pattern)


DEFAULT_COMMENT_STYLES: tuple[CommentStyle, ...] = (
    CommentStyle.HTML,
    CommentStyle.HASH,
    CommentStyle.JS,
    CommentStyle.BLOCK,
)


@dataclass(frozen=True)
class InsertionBlock:
    """A single repolish insertion block parsed from a file."""

    tag: str
    function: str
    args: tuple[str, ...] = field(default_factory=tuple)
    body: str = ''
    start: int = 0
    end: int = 0
    body_start: int = 0
    body_end: int = 0
    comment_style: CommentStyle = CommentStyle.HTML


@dataclass(frozen=True)
class ParsedInsertions:
    """The parsed result for a file containing insertion blocks."""

    text: str
    blocks: list[InsertionBlock] = field(default_factory=list)

    @property
    def has_insertions(self) -> bool:
        """True when at least one insertion block was found in the file."""
        return bool(self.blocks)
