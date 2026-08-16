"""Insertion block parsing and application for repolish-managed file slots."""

from repolish.insertions.models import (
    CommentStyle,
    InsertionBlock,
    ParsedInsertions,
)
from repolish.insertions.parser import parse_file, parse_text

__all__ = [
    'CommentStyle',
    'InsertionBlock',
    'ParsedInsertions',
    'parse_file',
    'parse_text',
]
