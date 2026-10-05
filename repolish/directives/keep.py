"""Keep-block directive processing for templates.

This module handles explicit developer-owned regions that should be preserved
from the current project file when present.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hotlog import get_logger

if TYPE_CHECKING:
    import re

from repolish.directives.definitions import (
    KEEP_BLOCK_DIRECTIVE_RE,
    KEEP_HEADER_DIRECTIVE_RE,
    KEEP_REST_DIRECTIVE_RE,
    DirectiveMapDefinition,
    extract_directive_map,
)
from repolish.directives.phases import (
    split_directive_tag,
)
from repolish.marker_kit import (
    OccurrenceTracker,
    RegionBoundary,
    find_all_bounded_regions,
    find_bounded_regions_in_range,
    find_first_line_index,
    occurrence_key,
)

logger = get_logger(__name__)

# Bounded keep regions are the shared RegionBoundary under its classic name;
# kept as an alias because internal tests import KeepBlockSpec from here.
KeepBlockSpec = RegionBoundary


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


def extract_keep_patterns(
    content: str,
    phase: str,
    source_path: str | None = None,
) -> KeepPatterns:
    """Extract all keep directives from *content* for the selected *phase*."""
    blocks = extract_directive_map(
        content,
        _KEEP_BLOCK_EXTRACT_DEF,
        phase=phase,
        source_path=source_path,
    )
    rest = extract_directive_map(
        content,
        _KEEP_REST_EXTRACT_DEF,
        phase=phase,
        source_path=source_path,
    )
    header = extract_directive_map(
        content,
        _KEEP_HEADER_EXTRACT_DEF,
        phase=phase,
        source_path=source_path,
    )
    return KeepPatterns(blocks=blocks, rest=rest, header=header)


def _parse_keep_literal(raw: str) -> str:
    """Parse a quoted keep directive literal."""
    value = ast.literal_eval(raw)
    if not isinstance(value, str):
        msg = 'keep directive values must be quoted strings'
        raise TypeError(msg)
    return value


def _parse_keep_block_spec(
    start_mode: str,
    start_raw: str,
    end_mode: str,
    end_raw: str,
) -> KeepBlockSpec:
    """Parse keep-block bounds supporting literal/regex start and end."""
    start_value = _parse_keep_literal(start_raw)
    end_value = _parse_keep_literal(end_raw)
    start_regex = start_value if start_mode == 'start-regex' else None
    start = '' if start_regex is not None else start_value
    if end_mode == 'end':
        return KeepBlockSpec(
            start=start,
            end=end_value,
            start_regex=start_regex,
        )
    return KeepBlockSpec(
        start=start,
        end_regex=end_value,
        start_regex=start_regex,
    )


_KEEP_BLOCK_EXTRACT_DEF = DirectiveMapDefinition(
    pattern=KEEP_BLOCK_DIRECTIVE_RE,
    parse_value=_parse_keep_block_spec,
)

_KEEP_REST_EXTRACT_DEF = DirectiveMapDefinition(
    pattern=KEEP_REST_DIRECTIVE_RE,
    parse_value=lambda marker_raw: KeepMarkerSpec(
        marker=_parse_keep_literal(marker_raw),
    ),
)

_KEEP_HEADER_EXTRACT_DEF = DirectiveMapDefinition(
    pattern=KEEP_HEADER_DIRECTIVE_RE,
    parse_value=lambda marker_raw: KeepMarkerSpec(
        marker=_parse_keep_literal(marker_raw),
    ),
)


@dataclass(frozen=True)
class _KeepApplyContext:
    """Shared context used while applying keep directives."""

    template_lines: list[str]
    local_lines: list[str]
    patterns: KeepPatterns
    keep_block_occurrence: OccurrenceTracker[tuple[str, str, str, str]]
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
        keep_block_occurrence=OccurrenceTracker(),
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


@dataclass(frozen=True)
class _BlockClaim:
    """One keep-block spec resolved against the segment its run governs."""

    name: str
    template_regions: list[tuple[int, int]]
    occurrence_start: int
    local_regions: list[tuple[int, int]]

    def paired_local_region(self, offset: int) -> tuple[int, int] | None:
        """Return the local region paired with template region *offset*, if any."""
        index = self.occurrence_start + offset
        if index < len(self.local_regions):
            return self.local_regions[index]
        return None


def _apply_keep_block(
    result: list[str],
    directive_index: int,
    match: re.Match[str],
    ctx: _KeepApplyContext,
) -> tuple[list[str], int]:
    """Apply one keep-block directive together with any stacked run below it.

    Consecutive keep-block directive lines form a single run governing one
    shared segment (from below the run up to the next keep directive): each
    spec claims the regions matching its own markers anywhere in that
    segment, so stacked directives all manage their regions instead of only
    the last one. A lone directive keeps the interleaved semantics — its
    segment ends where the next keep directive begins.
    """
    matches = _stacked_block_directives(directive_index, match, ctx)
    content_start = directive_index + len(matches)
    segment_end = _find_next_keep_directive_index(
        ctx.template_lines,
        content_start,
        ctx.phase,
        source_path=ctx.source_path,
    )
    if segment_end is None:
        segment_end = len(ctx.template_lines)

    claims = _collect_block_claims(matches, content_start, segment_end, ctx)
    _emit_block_segment(result, claims, content_start, segment_end, ctx)
    return result, segment_end


def _stacked_block_directives(
    directive_index: int,
    first_match: re.Match[str],
    ctx: _KeepApplyContext,
) -> list[re.Match[str]]:
    """Collect the run of consecutive keep-block directive lines, first included.

    Only keep-block lines join a run; keep-rest/keep-header keep their own
    single-directive semantics.
    """
    matches = [first_match]
    lines = ctx.template_lines
    index = directive_index + 1
    while index < len(lines):
        stripped = lines[index].rstrip('\r\n')
        stacked = _KEEP_BLOCK_RE.match(stripped)
        if stacked is None or not _is_phase_selected(
            stacked,
            ctx.phase,
            source_path=ctx.source_path,
        ):
            break
        matches.append(stacked)
        index += 1
    return matches


def _collect_block_claims(
    matches: list[re.Match[str]],
    content_start: int,
    segment_end: int,
    ctx: _KeepApplyContext,
) -> list[_BlockClaim]:
    """Resolve each directive in the run into its claimed regions and pairings.

    Occurrence batches are taken in directive order, so interleaved templates
    pair first-to-first exactly as before.
    """
    claims: list[_BlockClaim] = []
    for match in matches:
        name = _directive_name(match.group(1), source_path=ctx.source_path)
        spec = ctx.patterns.blocks.get(name)
        if spec is None:
            logger.debug('keep_block_no_match_in_target', name=name)
            continue
        template_regions = find_bounded_regions_in_range(
            ctx.template_lines,
            content_start,
            segment_end,
            spec,
        )
        if not template_regions:
            logger.warning('keep_block_template_region_not_found', name=name)
            continue
        claims.append(
            _BlockClaim(
                name=name,
                template_regions=template_regions,
                occurrence_start=ctx.keep_block_occurrence.take(
                    occurrence_key(spec),
                    len(template_regions),
                ),
                local_regions=find_all_bounded_regions(ctx.local_lines, spec),
            ),
        )
    return claims


def _sorted_claim_spans(
    claims: list[_BlockClaim],
) -> list[tuple[tuple[int, int], int, _BlockClaim]]:
    """Flatten claimed regions into (region, offset, claim) spans in file order."""
    spans: list[tuple[tuple[int, int], int, _BlockClaim]] = []
    for claim in claims:
        for offset, region in enumerate(claim.template_regions):
            spans.append((region, offset, claim))
    spans.sort(key=lambda span: span[0][0])
    return spans


def _emit_block_segment(
    result: list[str],
    claims: list[_BlockClaim],
    content_start: int,
    segment_end: int,
    ctx: _KeepApplyContext,
) -> None:
    """Emit the shared segment once, splicing each claimed region's content.

    A region overlapped by an earlier claim's already-emitted content is
    skipped, so stacked specs sharing the same markers never emit a region
    twice.
    """
    cursor = content_start
    matched_names: set[str] = set()
    for region, offset, claim in _sorted_claim_spans(claims):
        if region[0] < cursor:
            continue
        result.extend(ctx.template_lines[cursor : region[0]])
        local_region = claim.paired_local_region(offset)
        if local_region is None:
            result.extend(ctx.template_lines[region[0] : region[1] + 1])
        else:
            result.extend(ctx.local_lines[local_region[0] : local_region[1] + 1])
            matched_names.add(claim.name)
        cursor = region[1] + 1

    result.extend(ctx.template_lines[cursor:segment_end])
    _log_block_claims(claims, matched_names)


def _log_block_claims(claims: list[_BlockClaim], matched_names: set[str]) -> None:
    """Report per directive whether any local region was spliced."""
    for claim in claims:
        event = 'keep_block_matched_in_target' if claim.name in matched_names else 'keep_block_no_match_in_target'
        logger.debug(event, name=claim.name)


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

    template_marker_index = find_first_line_index(
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

    local_marker_index = find_first_line_index(
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

    template_marker_index = find_first_line_index(
        ctx.template_lines,
        spec.marker,
        start=directive_index + 1,
    )
    if template_marker_index is None:
        logger.warning('keep_header_marker_not_found_in_template', name=name)
        return result, directive_index + 1

    local_marker_index = find_first_line_index(
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
