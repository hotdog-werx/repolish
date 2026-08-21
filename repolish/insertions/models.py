"""Models for insertion markers and parsed file content."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from repolish.providers.models.context import RepolishContext


class CommentStyle(StrEnum):
    """Supported comment syntaxes for insertion markers."""

    HTML = 'html'
    HASH = 'hash'
    JS = 'js'
    BLOCK = 'block'

    @property
    def pattern(self) -> str:
        """Return a regex pattern for this comment style."""
        # Use [^\S\n\r]+ to match whitespace without crossing newlines
        if self is CommentStyle.HTML:
            return r'<!--\s*repolish:(?P<kind>on|off):?(?P<tag>[^\s>]*)(?:\s+(?P<body>[^\n\r]*))?\s*-->'
        if self is CommentStyle.HASH:
            return (
                r'(?m)^(?:\s*#\s*repolish:(?P<kind>on|off):?(?P<tag>[^\s]*)'
                r'(?:[^\S\n\r]+(?P<body>[^\n\r]*))?\s*)$'
            )
        if self is CommentStyle.JS:
            return (
                r'(?m)^(?:\s*//\s*repolish:(?P<kind>on|off):?(?P<tag>[^\s]*)'
                r'(?:[^\S\n\r]+(?P<body>[^\n\r]*))?\s*)$'
            )
        if self is CommentStyle.BLOCK:
            return (
                r'(?m)^(?:\s*/\*\s*repolish:(?P<kind>on|off):?(?P<tag>[^\s]*)'
                r'(?:[^\S\n\r]+(?P<body>[^\n\r]*))?\s*\*/\s*)$'
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
class BlockContext:
    """Context passed to insertion functions when requested via signature.

    This is injected automatically if the function signature includes a
    keyword-only parameter annotated with `BlockContext`.

    Attributes:
        tag: The insertion block's tag name (e.g., 'year', 'env').
        args: Positional arguments from the marker as strings.
        repolish: The full repolish context (workspace, repo, year, provider info).
        provider_context: Optional provider-specific context (set by provider).
        file_path: The path of the file where the insertion block is defined.
        insertion_block: The full InsertionBlock for convenience access.
    """

    tag: str
    args: tuple[str, ...]
    repolish: RepolishContext
    insertion_block: InsertionBlock
    provider_context: Any
    file_path: str = ''


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
    file_path: str = ''


@dataclass(frozen=True)
class ParseDiagnostic:
    """A structured summary of a parse failure."""

    message: str
    position: int | None = None


@dataclass(frozen=True)
class ParsedInsertions:
    """The parsed result for a file containing insertion blocks."""

    text: str
    blocks: list[InsertionBlock] = field(default_factory=list)
    diagnostics: list[ParseDiagnostic] = field(default_factory=list)

    @property
    def has_insertions(self) -> bool:
        """True when at least one insertion block was found in the file."""
        return bool(self.blocks)
