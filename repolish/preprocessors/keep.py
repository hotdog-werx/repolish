"""Keep-block preprocessing for templates.

This module handles explicit developer-owned regions that should be preserved
from the current project file when present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hotlog import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class KeepBlockSpec:
    """A bounded keep region defined by explicit start and end markers."""

    start: str
    end: str


@dataclass(frozen=True)
class KeepMarkerSpec:
    """A single marker used for keep-rest or keep-header directives."""

    marker: str


@dataclass(frozen=True)
class _KeepApplyContext:
    """Shared context used while applying keep directives."""

    template_lines: list[str]
    local_lines: list[str]
    keep_blocks: dict[str, KeepBlockSpec]
    keep_rest: dict[str, KeepMarkerSpec]
    keep_header: dict[str, KeepMarkerSpec]
    keep_block_occurrence: dict[tuple[str, str], int]


_KEEP_BLOCK_RE = re.compile(
    r'^[^\n]*repolish-keep-block\[(.+?)\]:\s*start=("(?:\\.|[^"])*")\s+end=("(?:\\.|[^"])*")[^\n]*$',
)
_KEEP_REST_RE = re.compile(
    r'^[^\n]*repolish-keep-(?:rest|the-rest|footer)\[(.+?)\]:\s*marker=("(?:\\.|[^"])*")[^\n]*$',
)
_KEEP_HEADER_RE = re.compile(
    r'^[^\n]*repolish-keep-(?:header|the-header)\[(.+?)\]:\s*marker=("(?:\\.|[^"])*")[^\n]*$',
)


def apply_keep_replacements(
    content: str,
    keep_blocks: dict[str, KeepBlockSpec],
    keep_rest: dict[str, KeepMarkerSpec],
    keep_header: dict[str, KeepMarkerSpec],
    local_file_content: str,
) -> str:
    """Apply keep directives to template content.

    Keep directives are stripped from the final output. When a matching region
    exists in the local file, that region wins; otherwise the template's own
    default region is preserved.
    """
    logger.debug(
        'applying_keep_replacements',
        keep_blocks=[str(name) for name in keep_blocks],
        keep_rest=[str(name) for name in keep_rest],
        keep_header=[str(name) for name in keep_header],
    )
    template_lines = content.splitlines(keepends=True)
    local_lines = local_file_content.splitlines(keepends=True)
    ctx = _KeepApplyContext(
        template_lines=template_lines,
        local_lines=local_lines,
        keep_blocks=keep_blocks,
        keep_rest=keep_rest,
        keep_header=keep_header,
        keep_block_occurrence={},
    )
    result: list[str] = []

    index = 0
    while index < len(template_lines):
        line = template_lines[index]

        block_match = _KEEP_BLOCK_RE.match(line.rstrip('\n'))
        if block_match:
            result, index = _apply_keep_block(result, index, block_match, ctx)
            continue

        rest_match = _KEEP_REST_RE.match(line.rstrip('\n'))
        if rest_match:
            result, index = _apply_keep_rest(result, index, rest_match, ctx)
            continue

        header_match = _KEEP_HEADER_RE.match(line.rstrip('\n'))
        if header_match:
            result, index = _apply_keep_header(result, index, header_match, ctx)
            continue

        result.append(line)
        index += 1

    return ''.join(result)


def _apply_keep_block(
    result: list[str],
    directive_index: int,
    match: re.Match[str],
    ctx: _KeepApplyContext,
) -> tuple[list[str], int]:
    name = match.group(1)
    spec = ctx.keep_blocks.get(name)
    if spec is None:
        logger.debug('keep_block_no_match_in_target', name=name)
        return result, directive_index + 1

    segment_end = _find_next_keep_directive_index(
        ctx.template_lines,
        directive_index + 1,
    )
    if segment_end is None:
        segment_end = len(ctx.template_lines)

    template_regions = _find_bounded_regions_in_range(
        ctx.template_lines,
        directive_index + 1,
        segment_end,
        spec.start,
        spec.end,
    )
    if not template_regions:
        logger.warning('keep_block_template_region_not_found', name=name)
        return result, directive_index + 1

    marker_key = (spec.start, spec.end)
    occurrence_start = ctx.keep_block_occurrence.get(marker_key, 0)
    local_regions = _find_all_bounded_regions(
        ctx.local_lines,
        spec.start,
        spec.end,
    )

    cursor = directive_index + 1
    matched_any = False
    for offset, template_region in enumerate(template_regions):
        result.extend(ctx.template_lines[cursor : template_region[0]])
        local_index = occurrence_start + offset
        if local_index < len(local_regions):
            local_region = local_regions[local_index]
            result.extend(
                ctx.local_lines[local_region[0] : local_region[1] + 1],
            )
            matched_any = True
        else:
            result.extend(
                ctx.template_lines[template_region[0] : template_region[1] + 1],
            )
        cursor = template_region[1] + 1

    result.extend(ctx.template_lines[cursor:segment_end])
    ctx.keep_block_occurrence[marker_key] = occurrence_start + len(
        template_regions,
    )

    if matched_any:
        logger.debug('keep_block_matched_in_target', name=name)
    else:
        logger.debug('keep_block_no_match_in_target', name=name)
    return result, segment_end


def _apply_keep_rest(
    result: list[str],
    directive_index: int,
    match: re.Match[str],
    ctx: _KeepApplyContext,
) -> tuple[list[str], int]:
    name = match.group(1)
    spec = ctx.keep_rest.get(name)
    if spec is None:
        logger.debug('keep_rest_no_match_in_target', name=name)
        return result, directive_index + 1

    template_marker_index = _find_first_line_index(
        ctx.template_lines,
        spec.marker,
        start=directive_index + 1,
    )
    if template_marker_index is None:
        logger.warning('keep_rest_marker_not_found_in_template', name=name)
        return result, directive_index + 1

    local_marker_index = _find_first_line_index(
        ctx.local_lines,
        spec.marker,
        start=0,
    )
    if local_marker_index is None:
        logger.debug('keep_rest_no_match_in_target', name=name)
        result.extend(ctx.template_lines[template_marker_index:])
    else:
        logger.debug('keep_rest_matched_in_target', name=name)
        result.extend(ctx.local_lines[local_marker_index:])
    return result, len(ctx.template_lines)


def _apply_keep_header(
    result: list[str],
    directive_index: int,
    match: re.Match[str],
    ctx: _KeepApplyContext,
) -> tuple[list[str], int]:
    name = match.group(1)
    spec = ctx.keep_header.get(name)
    if spec is None:
        logger.debug('keep_header_no_match_in_target', name=name)
        return result, directive_index + 1

    template_marker_index = _find_first_line_index(
        ctx.template_lines,
        spec.marker,
        start=directive_index + 1,
    )
    if template_marker_index is None:
        logger.warning('keep_header_marker_not_found_in_template', name=name)
        return result, directive_index + 1

    local_marker_index = _find_first_line_index(
        ctx.local_lines,
        spec.marker,
        start=0,
    )
    if local_marker_index is None:
        logger.debug('keep_header_no_match_in_target', name=name)
        prefix_end = template_marker_index + 1
        result.extend(ctx.template_lines[directive_index + 1 : prefix_end])
    else:
        logger.debug('keep_header_matched_in_target', name=name)
        prefix_end = local_marker_index + 1
        result.extend(ctx.local_lines[:prefix_end])

    result.extend(ctx.template_lines[template_marker_index + 1 :])
    return result, len(ctx.template_lines)


def _find_first_line_index(
    lines: list[str],
    marker: str,
    *,
    start: int,
) -> int | None:
    """Return the first line index whose content matches *marker* exactly."""
    for index in range(start, len(lines)):
        if lines[index].rstrip('\n') == marker:
            return index
    return None


def _find_bounded_region(
    lines: list[str],
    start_index: int,
    start_marker: str,
    end_marker: str,
) -> tuple[int, int] | None:
    """Return the inclusive line span for a bounded keep block."""
    bounded_start_index = _find_first_line_index(
        lines,
        start_marker,
        start=start_index,
    )
    if bounded_start_index is None:
        return None
    end_index = _find_first_line_index(
        lines,
        end_marker,
        start=bounded_start_index + 1,
    )
    if end_index is None:
        return None
    return bounded_start_index, end_index


def _find_all_bounded_regions(
    lines: list[str],
    start_marker: str,
    end_marker: str,
) -> list[tuple[int, int]]:
    """Return all bounded regions for a repeated marker pair."""
    regions: list[tuple[int, int]] = []
    search_start = 0
    while search_start < len(lines):
        region = _find_bounded_region(
            lines,
            search_start,
            start_marker,
            end_marker,
        )
        if region is None:
            break
        regions.append(region)
        search_start = region[1] + 1
    return regions


def _find_bounded_regions_in_range(
    lines: list[str],
    start_index: int,
    end_index: int,
    start_marker: str,
    end_marker: str,
) -> list[tuple[int, int]]:
    """Return bounded regions fully contained between start_index and end_index."""
    regions: list[tuple[int, int]] = []
    search_start = start_index
    while search_start < end_index:
        region = _find_bounded_region(
            lines,
            search_start,
            start_marker,
            end_marker,
        )
        if region is None or region[0] >= end_index or region[1] >= end_index:
            break
        regions.append(region)
        search_start = region[1] + 1
    return regions


def _find_next_keep_directive_index(
    lines: list[str],
    start: int,
) -> int | None:
    """Return the next keep directive line index at or after *start*."""
    for index in range(start, len(lines)):
        stripped = lines[index].rstrip('\n')
        if _KEEP_BLOCK_RE.match(stripped) or _KEEP_REST_RE.match(stripped) or _KEEP_HEADER_RE.match(stripped):
            return index
    return None
