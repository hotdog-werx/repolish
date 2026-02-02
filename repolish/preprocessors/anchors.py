"""Anchor-based preprocessing for templates.

This module handles anchor/tag block replacements in templates, where content
between repolish-start[tag] and repolish-end[tag] markers can be replaced.
"""

import re

from hotlog import get_logger

logger = get_logger(__name__)


def replace_tags_in_content(content: str, tags: dict[str, str]) -> str:
    """Replaces tag blocks in the content with provided tag values.

    Args:
        content: The original content containing tag blocks.
        tags: A dictionary mapping tag names to their replacement values.

    Returns:
        The content with the tags replaced by their corresponding values.
    """
    logger.debug('replacing_tags', tags=[str(tag) for tag in tags])
    for tag, value in tags.items():
        # Build a pattern that matches a whole start line containing the token
        # `repolish-start[tag]`, then captures the inner block, then matches
        # the end line containing `repolish-end[tag]`. This allows comment
        # prefixes/suffixes on the marker lines.
        # Match entire block including optional leading/trailing newline so
        # the replacement doesn't leave extra blank lines.
        pattern = re.compile(
            r'\n?[^\n]*repolish-start\[' + re.escape(tag) + r'\][^\n]*\n'
            r'(.*?)[^\n]*repolish-end\[' + re.escape(tag) + r'\][^\n]*\n?',
            re.DOTALL | re.MULTILINE,
        )
        content = pattern.sub(lambda _m, v=value: f'\n{v}\n', content)
    return content
