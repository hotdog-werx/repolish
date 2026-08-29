"""Regex-based preprocessing for templates.

This module handles regex pattern extraction and replacement in templates,
including support for capture groups and indentation-aware trimming.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hotlog import get_logger

from repolish.preprocessors.directive_phase import directive_phase_of
from repolish.preprocessors.directives import REGEX_DIRECTIVE_RE

logger = get_logger(__name__)


@dataclass(frozen=True)
class _MatchedRegion:
    """Holds the trimmed region and its boundaries for a regex match."""

    content: str
    start: int
    end: int


_REGEX_DIRECTIVE_RE = REGEX_DIRECTIVE_RE


def _select_capture(match: re.Match) -> str:
    """Return the author's intended capture from a regex match.

    If the regex contains capturing groups, prefer the first group
    (group 1). Otherwise fall back to the full match (group 0).
    This lets regex authors precisely specify what should be
    extracted and inserted.
    """
    if match.lastindex:
        # prefer the first capture group when present
        return match.group(1)
    return match.group(0)


def _trim_block_by_indent(block: str) -> str:
    """Trim a matched block to the contiguous, same-indentation region.

    Keeps the first line and any immediately following lines that are
    either blank or indented at least as far as the first line. Stops at
    the first subsequent line with smaller indentation. This heuristic is
    intentionally simple and works well for indentation-based formats
    (YAML, Python-ish lists, etc.) but is only a safeguard — authors
    should prefer explicit capture groups to precisely control what to
    extract.
    """
    lines = block.splitlines(keepends=True)
    if not lines:
        return block
    first = lines[0]
    anchor_indent = len(first) - len(first.lstrip(' '))
    kept = [first]
    for ln in lines[1:]:
        if ln.strip() == '':
            kept.append(ln)
            continue
        indent = len(ln) - len(ln.lstrip(' '))
        if indent >= anchor_indent:
            kept.append(ln)
        else:
            break
    return ''.join(kept)


def _extend_trimmed_region_to_include_whitespace(
    content: str,
    trimmed_end: int,
    tpl_cap_end: int,
) -> int:
    """Preserve trailing whitespace-only content from the original capture."""
    if trimmed_end < tpl_cap_end:
        between = content[trimmed_end:tpl_cap_end]
        if between.strip() == '' and '\n' in between:
            return tpl_cap_end
    return trimmed_end


def _find_template_match(
    pattern: re.Pattern[str],
    content: str,
) -> _MatchedRegion | None:
    """Find and trim a regex match in template content.

    Returns None if no match is found (caller should skip this regex).
    Otherwise returns the trimmed region with its boundaries.
    """
    template_match = pattern.search(content)
    offset = 0

    if not template_match:
        fallback = _search_indented_template_match(pattern, content)
        if fallback is None:
            return None
        template_match, offset = fallback

    # Determine which group index we used (1 for capture group, 0 for full match)
    group_idx = 1 if template_match.lastindex else 0
    cap_start, cap_end = template_match.span(group_idx)
    cap_start += offset
    cap_end += offset

    # Extract and trim the matched content
    matched_raw = content[cap_start:cap_end]
    matched = _trim_block_by_indent(matched_raw)

    # Compute the trimmed region boundaries
    trimmed_start = cap_start
    trimmed_end = cap_start + len(matched)
    trimmed_end = _extend_trimmed_region_to_include_whitespace(
        content,
        trimmed_end,
        cap_end,
    )

    return _MatchedRegion(content=matched, start=trimmed_start, end=trimmed_end)


def apply_regex_replacements(
    content: str,
    regexes: dict[str, str],
    local_file_content: str,
    *,
    phase: str = 'pre-render',
) -> str:
    """Applies regex replacements to the content."""
    content = _strip_regex_directives_for_phase(content, phase)
    logger.debug(
        'applying_regex_replacements',
        regexes=[str(name) for name in regexes],
    )

    for regex_name, regex_pattern in regexes.items():
        pattern = re.compile(rf'{regex_pattern}', re.MULTILINE)

        # Check local file for a match
        local_match = pattern.search(local_file_content)
        if not local_match:
            logger.debug(
                'regex_no_match_in_target',
                regex=regex_name,
                pattern=regex_pattern,
            )
            continue

        logger.debug(
            'regex_matched_in_target',
            regex=regex_name,
            matched=_select_capture(local_match),
        )

        # Get the trimmed content from local file
        local_matched_raw = _select_capture(local_match)
        local_matched = _trim_block_by_indent(local_matched_raw)

        # Find the region to replace in the template
        region = _find_template_match(pattern, content)
        if region is None:
            # nothing to replace in template
            continue

        # Replace the matched region with local content
        content = content[: region.start] + local_matched + content[region.end :]

    return content


def _search_indented_template_match(
    pattern: re.Pattern[str],
    content: str,
) -> tuple[re.Match[str], int] | None:
    """Match a pattern against an indented single line and return its offset."""
    offset = 0
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip(' \t')
        if not stripped:
            offset += len(line)
            continue

        line_body = stripped.rstrip('\r\n')
        match = pattern.fullmatch(line_body)
        if match:
            return match, offset + (len(line) - len(stripped))
        offset += len(line)
    return None


def _strip_regex_directives_for_phase(content: str, phase: str) -> str:
    """Remove only regex directive lines assigned to the selected phase."""
    result: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.rstrip('\r\n')
        match = _REGEX_DIRECTIVE_RE.match(stripped)
        if match and directive_phase_of(match.group(1)) == phase:
            continue
        result.append(line)
    return ''.join(result)
