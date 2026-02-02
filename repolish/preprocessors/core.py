"""Core preprocessing utilities for templates.

This module provides the main functions for extracting patterns from templates,
replacing tags, and orchestrating the complete text replacement pipeline.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from hotlog import get_logger

from repolish.preprocessors.anchors import replace_tags_in_content
from repolish.preprocessors.multiregex import apply_multiregex_replacements
from repolish.preprocessors.regex import apply_regex_replacements

logger = get_logger(__name__)


@dataclass
class Patterns:
    """Container for extracted patterns from content."""

    tag_blocks: dict[str, str]
    regexes: dict[str, str]
    multiregex_blocks: dict[str, str]
    multiregexes: dict[str, str]


def extract_patterns(content: str) -> Patterns:
    """Extracts text blocks and regex patterns from the given content.

    Args:
        content: The input string containing text blocks and regex patterns.

    Returns:
        A Patterns object containing extracted tag blocks and regexes.
    """
    # Accept markers with optional prefixes (e.g. "## ", "<!-- ", "/* ") so
    # templates can use comment syntax appropriate to the file type. We match a
    # whole start line that contains `repolish-start[name]`, capture the
    # following block, and then match the corresponding end line.
    tag_pattern = re.compile(
        # allow empty inner block (no extra blank line required before end)
        r'^[^\n]*repolish-start\[(.+?)\][^\n]*\n(.*?)[^\n]*repolish-end\[\1\][^\n]*',
        re.DOTALL | re.MULTILINE,
    )

    # Match regex declarations likewise with optional prefixes on the same line
    regex_pattern = re.compile(
        r'^[^\n]*repolish-regex\[(.+?)\]: (.*?)\n',
        re.DOTALL | re.MULTILINE,
    )

    # Match multiregex block declarations
    multiregex_block_pattern = re.compile(
        r'^[^\n]*repolish-multiregex-block\[(.+?)\]: (.*?)\n',
        re.DOTALL | re.MULTILINE,
    )

    # Match multiregex declarations
    multiregex_pattern = re.compile(
        r'^[^\n]*repolish-multiregex\[(.+?)\]: (.*?)\n',
        re.DOTALL | re.MULTILINE,
    )

    # Return the raw inner block content (no artificial padding). Strip any
    # leading/trailing newlines that are an artifact of how templates were
    # authored so callers get the pure inner text.
    raw_tag_blocks = dict(tag_pattern.findall(content))
    tag_blocks: dict[str, str] = {}
    for k, v in raw_tag_blocks.items():
        tag_blocks[k] = v.strip('\n')

    regexes = dict(regex_pattern.findall(content))
    multiregex_blocks = dict(multiregex_block_pattern.findall(content))
    multiregexes = dict(multiregex_pattern.findall(content))

    logger.debug(
        'extracted_patterns',
        tag_blocks=[str(k) for k in tag_blocks],
        regexes=[str(k) for k in regexes],
        multiregexes=[str(k) for k in multiregexes],
    )

    return Patterns(
        tag_blocks=tag_blocks,
        regexes=regexes,
        multiregex_blocks=multiregex_blocks,
        multiregexes=multiregexes,
    )


def safe_file_read(file_path: Path) -> str:
    """Safely reads the content of a file if it exists.

    Args:
        file_path: Path to the file to read.

    Returns:
        The content of the file, or an empty string if the file does not exist.
    """
    if file_path.exists() and file_path.is_file():
        return file_path.read_text()
    return ''


def replace_text(
    template_content: str,
    local_content: str,
    anchors_dictionary: dict[str, str] | None = None,
) -> str:
    """Replaces tag blocks and regex patterns in the template content.

    Args:
        template_content: The content of the template file.
        local_content: The content of the local file to extract patterns from.
        anchors_dictionary: Optional dictionary of anchor replacements provided by
            configuration (maps tag name -> replacement text). If provided, values
            in this dict will be used to replace corresponding `## repolish-start[...]` blocks
            in the template. If not provided, the template's own block contents are
            preserved.

    Returns:
        The modified template content with replaced tag blocks and regex patterns.
    """
    logger.debug(
        'starting_text_replacement',
        has_anchors=anchors_dictionary is not None,
    )
    patterns = extract_patterns(template_content)

    # Build the replacement mapping for tag blocks. If an anchors dictionary is
    # provided, use its values to replace the corresponding tag blocks. Otherwise
    # fall back to the template's own block content (i.e. leave defaults).
    tags_to_replace: dict[str, str] = {}
    for tag, default_value in patterns.tag_blocks.items():
        if anchors_dictionary and tag in anchors_dictionary:
            tags_to_replace[tag] = anchors_dictionary[tag]
        else:
            tags_to_replace[tag] = default_value

    content = replace_tags_in_content(template_content, tags_to_replace)
    content = apply_regex_replacements(content, patterns.regexes, local_content)
    content = apply_multiregex_replacements(
        content,
        patterns.multiregex_blocks,
        patterns.multiregexes,
        local_content,
    )
    result = content
    logger.debug(
        'text_replacement_completed',
        tag_blocks_replaced=len(tags_to_replace),
        regexes_applied=len(patterns.regexes),
        multiregexes_applied=len(patterns.multiregexes),
    )
    return result
