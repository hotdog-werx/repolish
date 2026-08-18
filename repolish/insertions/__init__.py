"""Insertion block parsing and application for repolish-managed file slots."""

from repolish.insertions.models import (
    BlockContext,
    CommentStyle,
    InsertionBlock,
    ParsedInsertions,
)
from repolish.insertions.parser import parse_text
from repolish.insertions.writer import (
    Renderer,
    WriteBackResult,
    WriteDiagnostic,
    write_back,
)

__all__ = [
    'BlockContext',
    'CommentStyle',
    'InsertionBlock',
    'ParsedInsertions',
    'Renderer',
    'WriteBackResult',
    'WriteDiagnostic',
    'parse_text',
    'write_back',
]
