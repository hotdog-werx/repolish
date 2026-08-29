"""Keep-block preprocessing for templates.

This module handles explicit developer-owned regions that should be preserved
from the current project file when present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hotlog import get_logger

from repolish.preprocessors.directive_phase import (
    split_directive_tag,
)
from repolish.preprocessors.directives import (
    KEEP_BLOCK_DIRECTIVE_RE,
    KEEP_HEADER_DIRECTIVE_RE,
    KEEP_REST_DIRECTIVE_RE,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class KeepBlockSpec:
    """A bounded keep region defined by explicit start and end markers."""

    start: str
    end: str | None = None
    end_regex: str | None = None


@dataclass(frozen=True)
class KeepMarkerSpec:
    """A single marker used for keep-rest or keep-header directives."""

    marker: str


@dataclass(frozen=True)
class KeepPatterns:
    """Container for all keep-related patterns extracted from a template."""

    blocks: dict[str, KeepBlockSpec]
    rest: dict[str, KeepMarkerSpec]
    header: dict[str, KeepMarkerSpec]


@dataclass(frozen=True)
class _KeepApplyContext:
    """Shared context used while applying keep directives."""

    template_lines: list[str]
    local_lines: list[str]
    patterns: KeepPatterns
    keep_block_occurrence: dict[tuple[str, str, str], int]
    phase: str
    source_path: str | None


_KEEP_BLOCK_RE = KEEP_BLOCK_DIRECTIVE_RE
_KEEP_REST_RE = KEEP_REST_DIRECTIVE_RE
_KEEP_HEADER_RE = KEEP_HEADER_DIRECTIVE_RE


def apply_keep_replacements(
    content: str,
    patterns: KeepPatterns,
    local_file_content: str,
    *,
    phase: str = 'pre-render',
    source_path: str | None = None,
) -> str:
    """Apply keep directives to template content.

    Keep directives are stripped from the final output. When a matching region
    exists in the local file, that region wins; otherwise the template's own
    default region is preserved.
    """
    logger.debug(
        'applying_keep_replacements',
        keep_blocks=[str(name) for name in patterns.blocks],
        keep_rest=[str(name) for name in patterns.rest],
        keep_header=[str(name) for name in patterns.header],
    )
    template_lines = content.splitlines(keepends=True)
    local_lines = local_file_content.splitlines(keepends=True)
    ctx = _KeepApplyContext(
        template_lines=template_lines,
        local_lines=local_lines,
        patterns=patterns,
        keep_block_occurrence={},
        phase=phase,
        source_path=source_path,
    )
    result: list[str] = []

    index = 0
    while index < len(template_lines):
        line = template_lines[index]
        stripped = line.rstrip('\r\n')

        block_match = _KEEP_BLOCK_RE.match(stripped)
        if block_match and _is_phase_selected(
            block_match,
            phase,
            source_path=source_path,
        ):
            result, index = _apply_keep_block(result, index, block_match, ctx)
            continue

        rest_match = _KEEP_REST_RE.match(stripped)
        if rest_match and _is_phase_selected(
            rest_match,
            phase,
            source_path=source_path,
        ):
            result, index = _apply_keep_rest(result, index, rest_match, ctx)
            continue

        header_match = _KEEP_HEADER_RE.match(stripped)
        if header_match and _is_phase_selected(
            header_match,
            phase,
            source_path=source_path,
        ):
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
    name = _directive_name(match.group(1), source_path=ctx.source_path)
    spec = ctx.patterns.blocks.get(name)
    if spec is None:
        logger.debug('keep_block_no_match_in_target', name=name)
        return result, directive_index + 1

    segment_end = _find_next_keep_directive_index(
        ctx.template_lines,
        directive_index + 1,
        ctx.phase,
        source_path=ctx.source_path,
    )
    if segment_end is None:
        segment_end = len(ctx.template_lines)

    template_regions = _find_bounded_regions_in_range(
        ctx.template_lines,
        directive_index + 1,
        segment_end,
        spec,
    )
    if not template_regions:
        logger.warning('keep_block_template_region_not_found', name=name)
        return result, directive_index + 1

    marker_key = _keep_block_occurrence_key(spec)
    occurrence_start = ctx.keep_block_occurrence.get(marker_key, 0)
    local_regions = _find_all_bounded_regions(
        ctx.local_lines,
        spec,
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
    name = _directive_name(match.group(1), source_path=ctx.source_path)
    spec = ctx.patterns.rest.get(name)
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

    # Keep provider-managed lines between directive and marker in output.
    result.extend(
        ctx.template_lines[directive_index + 1 : template_marker_index],
    )

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
    name = _directive_name(match.group(1), source_path=ctx.source_path)

    if directive_index != 0:
        logger.warning(
            'keep_header_must_be_at_file_start',
            name=name,
            directive_index=directive_index,
        )
        return result, directive_index + 1

    spec = ctx.patterns.header.get(name)
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
    """Return the first line index whose content matches *marker* exactly.

    Leading and trailing whitespace is stripped from the line before comparison
    to support keep blocks at any indentation level. This allows markers to be
    indented along with their surrounding content (e.g., inside YAML nested
    structures) and tolerates accidental trailing whitespace.
    """
    for index in range(start, len(lines)):
        if lines[index].strip() == marker:
            return index
    return None


def _find_bounded_region(
    lines: list[str],
    start_index: int,
    spec: KeepBlockSpec,
    *,
    end_limit_exclusive: int | None = None,
) -> tuple[int, int] | None:
    """Return the inclusive line span for a bounded keep block."""
    bounded_start_index = _find_first_line_index(
        lines,
        spec.start,
        start=start_index,
    )
    if bounded_start_index is None:
        return None
    if end_limit_exclusive is not None and bounded_start_index >= end_limit_exclusive:
        return None
    end_index = _find_end_line_index(
        lines,
        start=bounded_start_index + 1,
        spec=spec,
        end_limit_exclusive=end_limit_exclusive,
    )
    if end_index is None:
        return None
    return bounded_start_index, end_index


def _find_all_bounded_regions(
    lines: list[str],
    spec: KeepBlockSpec,
) -> list[tuple[int, int]]:
    """Return all bounded regions for a repeated marker pair."""
    regions: list[tuple[int, int]] = []
    search_start = 0
    while search_start < len(lines):
        region = _find_bounded_region(
            lines,
            search_start,
            spec,
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
    spec: KeepBlockSpec,
) -> list[tuple[int, int]]:
    """Return bounded regions fully contained between start_index and end_index."""
    regions: list[tuple[int, int]] = []
    search_start = start_index
    while search_start < end_index:
        region = _find_bounded_region(
            lines,
            search_start,
            spec,
            end_limit_exclusive=end_index,
        )
        if region is None or region[0] >= end_index or region[1] >= end_index:
            break
        regions.append(region)
        search_start = region[1] + 1
    return regions


def _find_next_keep_directive_index(
    lines: list[str],
    start: int,
    phase: str,
    source_path: str | None = None,
) -> int | None:
    """Return the next keep directive line index at or after *start*."""
    for index in range(start, len(lines)):
        stripped = lines[index].rstrip('\r\n')
        block_match = _KEEP_BLOCK_RE.match(stripped)
        rest_match = _KEEP_REST_RE.match(stripped)
        header_match = _KEEP_HEADER_RE.match(stripped)
        if (
            (
                block_match
                and _is_phase_selected(
                    block_match,
                    phase,
                    source_path=source_path,
                )
            )
            or (
                rest_match
                and _is_phase_selected(
                    rest_match,
                    phase,
                    source_path=source_path,
                )
            )
            or (
                header_match
                and _is_phase_selected(
                    header_match,
                    phase,
                    source_path=source_path,
                )
            )
        ):
            return index
    return None


def _find_end_line_index(
    lines: list[str],
    *,
    start: int,
    spec: KeepBlockSpec,
    end_limit_exclusive: int | None = None,
) -> int | None:
    """Return the end boundary index using literal `end` or `end_regex`."""
    limit = len(lines) if end_limit_exclusive is None else end_limit_exclusive
    if start >= limit:
        return None

    if spec.end is not None:
        return _find_end_index_by_marker(lines, start, limit, spec.end)

    if spec.end_regex is None:
        return None

    return _find_end_index_by_regex(lines, start, limit, spec.end_regex)


def _find_end_index_by_marker(
    lines: list[str],
    start: int,
    limit: int,
    marker: str,
) -> int | None:
    """Find the first line matching a literal marker between start and limit."""
    for index in range(start, limit):
        if lines[index].strip() == marker:
            return index
    return None


def _find_end_index_by_regex(
    lines: list[str],
    start: int,
    limit: int,
    end_regex: str,
) -> int:
    """Find the first regex end boundary, or close at the range end."""
    end_re = re.compile(end_regex)
    for index in range(start, limit):
        if end_re.search(lines[index].strip()):
            return index
    return limit - 1


def _keep_block_occurrence_key(spec: KeepBlockSpec) -> tuple[str, str, str]:
    """Build a stable occurrence key for repeated keep-block lookups."""
    return (
        spec.start,
        spec.end or '',
        spec.end_regex or '',
    )


def _is_phase_selected(
    match: re.Match[str],
    selected_phase: str,
    *,
    source_path: str | None = None,
) -> bool:
    """Return True when this keep directive should run in selected_phase."""
    _, directive_phase = split_directive_tag(
        match.group(1),
        source_path=source_path,
    )
    return directive_phase == selected_phase


def _directive_name(raw_name: str, *, source_path: str | None = None) -> str:
    """Return keep directive logical name without optional phase suffix."""
    name, _ = split_directive_tag(raw_name, source_path=source_path)
    return name
