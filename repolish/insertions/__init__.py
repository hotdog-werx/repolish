"""Insertion block parsing and application for repolish-managed file slots."""

from repolish.insertions.models import (
    CommentStyle,
    InsertionBlock,
    ParsedInsertions,
)
from repolish.insertions.parser import parse_file, parse_text
from repolish.insertions.writer import (
    Renderer,
    WriteBackResult,
    WriteDiagnostic,
    write_back,
    write_file,
)

__all__ = [
    'CommentStyle',
    'InsertionBlock',
    'ParsedInsertions',
    'Renderer',
    'WriteBackResult',
    'WriteDiagnostic',
    'parse_file',
    'parse_text',
    'write_back',
    'write_file',
]
