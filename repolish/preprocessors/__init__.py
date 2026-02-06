"""Preprocessing utilities for repolish templates.

This package contains utilities for preprocessing template files before they are
rendered with jinja. Preprocessing includes extracting patterns, applying regex
replacements, and handling special repolish markers.
"""

from repolish.preprocessors.anchors import replace_tags_in_content
from repolish.preprocessors.core import (
    Patterns,
    extract_patterns,
    replace_text,
    safe_file_read,
)
from repolish.preprocessors.multiregex import apply_multiregex_replacements
from repolish.preprocessors.regex import apply_regex_replacements

__all__ = [
    'Patterns',
    'apply_multiregex_replacements',
    'apply_regex_replacements',
    'extract_patterns',
    'replace_tags_in_content',
    'replace_text',
    'safe_file_read',
]
