"""Regex directive processing for templates.

This module handles regex pattern extraction and replacement in templates,
including support for capture groups and indentation-aware trimming.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hotlog import get_logger

from repolish.directives.definitions import (
    REGEX_DIRECTIVE_RE,
    DirectiveMapDefinition,
    extract_directive_map,
)
from repolish.directives.phases import directive_phase_of
from repolish.marker_kit import apply_splices

logger = get_logger(__name__)


def extract_regex_directives(
    content: str,
    phase: str,
    source_path: str | None = None,
) -> dict[str, str]:
    """Extract regex directives from *content* for the selected *phase*."""
    return extract_directive_map(
        content,
        _REGEX_EXTRACT_DEF,
        phase=phase,
        source_path=source_path,
    )


_REGEX_EXTRACT_DEF = DirectiveMapDefinition[str](
    pattern=REGEX_DIRECTIVE_RE,
    parse_value=lambda pattern: pattern,
)


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


def _trimmed_region(
    content: str,
    match: re.Match[str],
    offset: int = 0,
) -> _MatchedRegion:
    """Return the trimmed region for one regex match at *offset* in *content*."""
    # Determine which group index we used (1 for capture group, 0 for full match)
    group_idx = 1 if match.lastindex else 0
    cap_start, cap_end = match.span(group_idx)
    cap_start += offset
    cap_end += offset

    # Extract and trim the matched content
    matched = _trim_block_by_indent(content[cap_start:cap_end])

    # Compute the trimmed region boundaries
    trimmed_end = cap_start + len(matched)
    trimmed_end = _extend_trimmed_region_to_include_whitespace(
        content,
        trimmed_end,
        cap_end,
    )

    return _MatchedRegion(content=matched, start=cap_start, end=trimmed_end)


def _find_template_regions(
    pattern: re.Pattern[str],
    content: str,
) -> list[_MatchedRegion]:
    """Find every trimmed regex-match region in template content, in order.

    A plain scan supplies the regions; when it finds nothing, each line is
    tried as an indented full match (one region per matching line).
    """
    regions = [_trimmed_region(content, match) for match in pattern.finditer(content)]
    if regions:
        return regions
    return _find_indented_line_regions(pattern, content)


def _find_indented_line_regions(
    pattern: re.Pattern[str],
    content: str,
) -> list[_MatchedRegion]:
    """Match the pattern against indented single lines, one region per line."""
    regions: list[_MatchedRegion] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip(' \t')
        if stripped:
            line_body = stripped.rstrip('\r\n')
            match = pattern.fullmatch(line_body)
            if match:
                regions.append(_trimmed_region(content, match, offset + (len(line) - len(stripped))))
        offset += len(line)
    return regions


def _local_captures(
    pattern: re.Pattern[str],
    local_file_content: str,
) -> list[str]:
    """Return the trimmed capture of every local-file match, in order."""
    return [_trim_block_by_indent(_select_capture(match)) for match in pattern.finditer(local_file_content)]


def _pair_occurrences(
    regions: list[_MatchedRegion],
    local_captures: list[str],
) -> list[tuple[int, int, str]]:
    """Splice every template region against its first-to-first local pair."""
    return [
        (region.start, region.end, local_captures[offset])
        for offset, region in enumerate(regions)
        if offset < len(local_captures)
    ]


def apply_regex_replacements(
    content: str,
    regexes: dict[str, str],
    local_file_content: str,
    *,
    phase: str = 'pre-render',
) -> str:
    """Applies regex replacements to the content.

    Occurrences pair first-to-first: every template match is reconciled
    against the local file's matches in encounter order, so loop-generated
    duplicates all reconcile. Template matches beyond the local captures
    keep the template default; extra local matches are ignored.
    """
    content = _strip_regex_directives_for_phase(content, phase)
    logger.debug(
        'applying_regex_replacements',
        regexes=[str(name) for name in regexes],
    )

    for regex_name, regex_pattern in regexes.items():
        pattern = re.compile(rf'{regex_pattern}', re.MULTILINE)

        # Collect the local file's captures, in encounter order
        local_captures = _local_captures(pattern, local_file_content)
        if not local_captures:
            logger.debug(
                'regex_no_match_in_target',
                regex=regex_name,
                pattern=regex_pattern,
            )
            continue

        logger.debug(
            'regex_matched_in_target',
            regex=regex_name,
            matched=local_captures[0],
        )

        # Find every region to replace in the template
        regions = _find_template_regions(pattern, content)
        if not regions:
            # nothing to replace in template
            continue

        # Replace the paired regions with local content
        content = apply_splices(content, _pair_occurrences(regions, local_captures))

    return content


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
