"""Multi-regex preprocessing for templates.

This module handles multiregex pattern extraction and replacement, which allows
extracting multiple key-value pairs from a block and replacing them in sections.
"""

import re
from dataclasses import dataclass

from hotlog import get_logger

from repolish.preprocessors.directive_phase import (
    split_directive_tag,
)
from repolish.preprocessors.directives import (
    MULTIREGEX_BLOCK_DIRECTIVE_RE,
    MULTIREGEX_DIRECTIVE_RE,
    DirectiveMapDefinition,
    extract_directive_map,
)
from repolish.preprocessors.tag_names import parse_section_name

logger = get_logger(__name__)


@dataclass(frozen=True)
class MultiregexPatterns:
    """Container for all multiregex directives extracted from a template."""

    blocks: dict[str, str]
    regexes: dict[str, str]


def extract_multiregex_patterns(
    content: str,
    phase: str,
    source_path: str | None = None,
) -> MultiregexPatterns:
    """Extract all multiregex directives from *content* for the selected *phase*."""
    blocks = extract_directive_map(
        content,
        _MULTIREGEX_BLOCK_EXTRACT_DEF,
        phase=phase,
        source_path=source_path,
    )
    regexes = extract_directive_map(
        content,
        _MULTIREGEX_EXTRACT_DEF,
        phase=phase,
        source_path=source_path,
    )
    return MultiregexPatterns(blocks=blocks, regexes=regexes)


_MULTIREGEX_BLOCK_EXTRACT_DEF = DirectiveMapDefinition[str](
    pattern=MULTIREGEX_BLOCK_DIRECTIVE_RE,
    parse_value=lambda pattern: pattern,
)

_MULTIREGEX_EXTRACT_DEF = DirectiveMapDefinition[str](
    pattern=MULTIREGEX_DIRECTIVE_RE,
    parse_value=lambda pattern: pattern,
)

_MULTIREGEX_BLOCK_DIRECTIVE_RE = MULTIREGEX_BLOCK_DIRECTIVE_RE
_MULTIREGEX_DIRECTIVE_RE = MULTIREGEX_DIRECTIVE_RE

_KEY_VALUE_RE = re.compile(
    r'^(\s*)(")?([^"=:\s]+)(")?(\s*)([=:])(\s*)"([^"]*)"(.*)$',
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
        content = _remove_multiregex_comments(
            content,
            tag,
            phase,
        )
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


def _remove_multiregex_comments(
    content: str,
    tag: str,
    phase: str,
    *,
    source_path: str | None = None,
) -> str:
    """Remove multiregex directive lines for one tag and selected phase."""
    result: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.rstrip('\r\n')
        if _should_strip_directive_line(
            stripped,
            tag,
            phase,
            source_path=source_path,
        ):
            continue

        result.append(line)
    return ''.join(result)


def _should_strip_directive_line(
    stripped_line: str,
    tag: str,
    phase: str,
    *,
    source_path: str | None = None,
) -> bool:
    """Return whether a directive line matches the requested tag and phase."""
    for directive_pattern in (
        _MULTIREGEX_BLOCK_DIRECTIVE_RE,
        _MULTIREGEX_DIRECTIVE_RE,
    ):
        match = directive_pattern.match(stripped_line)
        if not match:
            continue

        raw_tag = match.group(1)
        directive_name, directive_phase = split_directive_tag(
            raw_tag,
            source_path=source_path,
        )

        if directive_name == tag and directive_phase == phase:
            return True

    return False


def _replace_values_in_section(
    content: str,
    tag: str,
    values: dict[str, str],
) -> str:
    """Replace template defaults using section mode or whole-file fallback."""
    lines = content.split('\n')
    if not any(_is_section_start(line, tag) for line in lines):
        return '\n'.join(_replace_values_in_lines(lines, values))

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


def _replace_values_in_lines(
    lines: list[str],
    values: dict[str, str],
) -> list[str]:
    """Replace matching key-value lines across the provided lines."""
    result: list[str] = []
    for line in lines:
        if _is_key_value_line(line):
            result.append(_replace_key_value(line, values))
            continue
        result.append(line)
    return result


def _is_section_start(line: str, tag: str) -> bool:
    """Check if the line starts a new section with the given tag."""
    return parse_section_name(line) == tag


def _is_section_exit(line: str, tag: str) -> bool:
    """Check if the line starts a new section, indicating exit from current tag section."""
    section_name = parse_section_name(line)
    return section_name is not None and section_name != tag


def _is_key_value_line(line: str) -> bool:
    """Check if the line is a quoted key=value or key:value assignment."""
    return bool(_KEY_VALUE_RE.match(line))


def _replace_key_value(line: str, values: dict[str, str]) -> str:
    """Replace the value in a key=value line if the key exists in values dict."""
    match = _KEY_VALUE_RE.match(line)
    if match:
        (
            indent,
            quote1,
            key,
            quote2,
            ws_before_sep,
            separator,
            ws_after_sep,
            default_value,
            suffix,
        ) = match.groups()
        actual_value = values.get(key, default_value or '')
        return ''.join(
            [
                f'{indent}{quote1 or ""}{key}{quote2 or ""}',
                f'{ws_before_sep}{separator}{ws_after_sep}"{actual_value}"{suffix}',
            ],
        )
    return line
