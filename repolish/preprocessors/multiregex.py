"""Multi-regex preprocessing for templates.

This module handles multiregex pattern extraction and replacement, which allows
extracting multiple key-value pairs from a block and replacing them in sections.
"""

import re

from hotlog import get_logger

logger = get_logger(__name__)

_MULTIREGEX_BLOCK_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-multiregex-block\[(.+?)\]:\s*(.*?)\s*$',
)
_MULTIREGEX_DIRECTIVE_RE = re.compile(
    r'^[^\n]*repolish-multiregex\[(.+?)\]:\s*(.*?)\s*$',
)


def apply_multiregex_replacements(
    content: str,
    multiregex_blocks: dict[str, str],
    multiregexes: dict[str, str],
    local_file_content: str,
    *,
    phase: str = 'pre-render',
) -> str:
    """Applies multiregex replacements to the content."""
    logger.debug(
        'applying_multiregex_replacements',
        multiregexes=[str(name) for name in multiregexes],
    )

    # Process each multiregex pair
    for tag, multi_regex in multiregexes.items():
        if tag not in multiregex_blocks:
            logger.debug('multiregex_missing_block', tag=tag)
            continue

        block_content = _extract_block_content(
            multiregex_blocks[tag],
            local_file_content,
            tag,
        )
        if block_content is None:
            continue

        values = _extract_values_from_block(multi_regex, block_content, tag)
        content = _remove_multiregex_comments(content, tag, phase)
        content = _replace_values_in_section(content, tag, values)

    return content


def _extract_block_content(
    block_regex: str,
    local_file_content: str,
    tag: str,
) -> str | None:
    """Extract block content from local file using regex."""
    block_re = re.compile(block_regex, re.DOTALL | re.MULTILINE)
    block_match = block_re.search(local_file_content)
    if not block_match:
        logger.debug(
            'multiregex_block_not_found_in_target',
            tag=tag,
            regex=block_regex,
        )
        return None

    block_content = block_match.group(1)
    logger.debug(
        'multiregex_block_extracted',
        tag=tag,
        block_length=len(block_content),
    )
    return block_content


def _extract_values_from_block(
    multi_regex: str,
    block_content: str,
    tag: str,
) -> dict[str, str]:
    """Extract key-value pairs from block content."""
    multi_re = re.compile(multi_regex, re.MULTILINE)
    matches = multi_re.findall(block_content)

    # Build dict of key to value (handle different capture group structures)
    values = {}
    for match in matches:
        if len(match) >= 4:  # Assuming format: (quote1, key, quote2, value)
            key = match[1]
            value = match[3]
            values[key] = value
        elif len(match) >= 2:  # Fallback for simpler formats
            key = match[0]
            value = match[1] if len(match) > 1 else ''
            values[key] = value

    logger.debug(
        'multiregex_values_extracted',
        tag=tag,
        values=list(values.keys()),
    )
    return values


def _remove_multiregex_comments(content: str, tag: str, phase: str) -> str:
    """Remove multiregex directive lines for one tag and selected phase."""
    result: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.rstrip('\r\n')
        block_match = _MULTIREGEX_BLOCK_DIRECTIVE_RE.match(stripped)
        if block_match and _directive_name(block_match.group(1)) == tag and _directive_phase(block_match) == phase:
            continue

        item_match = _MULTIREGEX_DIRECTIVE_RE.match(stripped)
        if item_match and _directive_name(item_match.group(1)) == tag and _directive_phase(item_match) == phase:
            continue

        result.append(line)
    return ''.join(result)


def _directive_phase(match: re.Match[str]) -> str:
    """Return directive phase parsed from tag suffix with pre-render default."""
    raw_tag = match.group(1)
    if '|' not in raw_tag:
        return 'pre-render'
    _, maybe_phase = raw_tag.rsplit('|', 1)
    return maybe_phase if maybe_phase in {'pre-render', 'after-render'} else 'pre-render'


def _directive_name(raw_tag: str) -> str:
    """Return the logical multiregex tag without an optional phase suffix."""
    if '|' not in raw_tag:
        return raw_tag
    name, maybe_phase = raw_tag.rsplit('|', 1)
    if maybe_phase in {'pre-render', 'after-render'} and name:
        return name
    return raw_tag


def _replace_values_in_section(
    content: str,
    tag: str,
    values: dict[str, str],
) -> str:
    """Replace template defaults with extracted values in the specified section."""
    lines = content.split('\n')
    result_lines = []
    in_section = False

    for line in lines:
        processed_line = line
        if _is_section_start(line, tag):
            in_section = True
        elif in_section and _is_section_exit(line, tag):
            in_section = False
        elif in_section and _is_key_value_line(line):
            processed_line = _replace_key_value(line, values)

        result_lines.append(processed_line)

    return '\n'.join(result_lines)


def _is_section_start(line: str, tag: str) -> bool:
    """Check if the line starts a new section with the given tag."""
    section_start_pattern = re.compile(r'^\[(\w+)\]')
    section_match = section_start_pattern.match(line.strip())
    return section_match is not None and section_match.group(1) == tag


def _is_section_exit(line: str, tag: str) -> bool:
    """Check if the line starts a new section, indicating exit from current tag section."""
    section_start_pattern = re.compile(r'^\[(\w+)\]')
    section_match = section_start_pattern.match(line.strip())
    return section_match is not None and section_match.group(1) != tag


def _is_key_value_line(line: str) -> bool:
    """Check if the line is a key=value assignment."""
    return bool(re.match(r'^\s*(")?([^"=\s]+)(")?\s*=\s*"([^"]*)"', line))


def _replace_key_value(line: str, values: dict[str, str]) -> str:
    """Replace the value in a key=value line if the key exists in values dict."""
    match = re.match(r'^\s*(")?([^"=\s]+)(")?\s*=\s*"([^"]*)"', line)
    if match:
        quote1, key, quote2, default_value = match.groups()
        actual_value = values.get(key, default_value or '')
        return f'{quote1 or ""}{key}{quote2 or ""} = "{actual_value}"'
    return line
