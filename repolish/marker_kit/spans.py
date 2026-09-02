"""Bounded marker regions over line lists, shared by marker-driven features.

Keep blocks — and region-based families such as provider insertion zones (the
4th quadrant) — need to locate ``start ... end``/``end-regex`` spans across
line lists, including repeated occurrences. The helpers here are line-indexed;
packages that work in char offsets (e.g. ``repolish.insertions``) keep their
own span type and share only :mod:`~repolish.marker_kit.pairing` and
:mod:`~repolish.marker_kit.splice`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RegionBoundary:
    """Markers delimiting a bounded region: literal start, literal end or regex."""

    start: str
    end: str | None = None
    end_regex: str | None = None


def find_first_line_index(
    lines: list[str],
    marker: str,
    *,
    start: int,
) -> int | None:
    """Return the first line index whose content matches *marker* exactly.

    Leading and trailing whitespace is stripped from the line before comparison
    to support regions at any indentation level. This allows markers to be
    indented along with their surrounding content (e.g., inside YAML nested
    structures) and tolerates accidental trailing whitespace.
    """
    for index in range(start, len(lines)):
        if lines[index].strip() == marker:
            return index
    return None


def find_bounded_region(
    lines: list[str],
    start_index: int,
    boundary: RegionBoundary,
    *,
    end_limit_exclusive: int | None = None,
) -> tuple[int, int] | None:
    """Return the inclusive line span for one bounded region."""
    bounded_start_index = find_first_line_index(
        lines,
        boundary.start,
        start=start_index,
    )
    if bounded_start_index is None:
        return None
    if end_limit_exclusive is not None and bounded_start_index >= end_limit_exclusive:
        return None
    end_index = _find_end_line_index(
        lines,
        start=bounded_start_index + 1,
        boundary=boundary,
        end_limit_exclusive=end_limit_exclusive,
    )
    if end_index is None:
        return None
    return bounded_start_index, end_index


def find_all_bounded_regions(
    lines: list[str],
    boundary: RegionBoundary,
) -> list[tuple[int, int]]:
    """Return all bounded regions for a repeated marker pair."""
    regions: list[tuple[int, int]] = []
    search_start = 0
    while search_start < len(lines):
        region = find_bounded_region(
            lines,
            search_start,
            boundary,
        )
        if region is None:
            break
        regions.append(region)
        search_start = region[1] + 1
    return regions


@dataclass(frozen=True)
class PrefixedRegion:
    """A bounded region whose opening line carries a trailing payload.

    Insertion-zone opening markers can carry arguments on the same line
    (``<!-- generated:badges:on my-org/my-repo -->``), so their opener is found
    by *prefix* rather than the exact match :data:`RegionBoundary` finders use.
    ``opening_args`` is the stripped text following the start prefix on the
    opening line.
    """

    start: int
    """Inclusive opening marker line index."""
    end: int
    """Inclusive closing line index."""
    opening_args: str
    """Text after the start prefix on the opening line (may be empty)."""


def find_prefixed_bounded_regions(
    lines: list[str],
    boundary: RegionBoundary,
) -> list[PrefixedRegion]:
    """Return all regions whose opening line *starts with* ``boundary.start``.

    Unlike :func:`find_all_bounded_regions`, the opener matches by prefix so
    trailing arguments on the marker line are tolerated and captured. The end
    boundary follows the same rules as :func:`find_bounded_region` (literal
    exact-strip match, or first ``end_regex`` match), except that an unmatched
    ``end_regex`` yields no region — an unbounded zone is skipped rather than
    allowed to swallow the rest of the file.
    """
    regions: list[PrefixedRegion] = []
    search_start = 0
    while search_start < len(lines):
        opening_index = _find_prefixed_opening(
            lines,
            boundary.start,
            start=search_start,
        )
        if opening_index is None:
            break
        end_index = _find_zone_end_line_index(
            lines,
            start=opening_index + 1,
            boundary=boundary,
        )
        if end_index is None:
            search_start = opening_index + 1
            continue
        opening_args = lines[opening_index].strip()[len(boundary.start) :].strip()
        regions.append(
            PrefixedRegion(
                start=opening_index,
                end=end_index,
                opening_args=opening_args,
            ),
        )
        search_start = end_index + 1
    return regions


def _find_prefixed_opening(
    lines: list[str],
    start_prefix: str,
    *,
    start: int,
) -> int | None:
    """Return the first line index whose stripped content starts with *start_prefix*."""
    for index in range(start, len(lines)):
        if lines[index].strip().startswith(start_prefix):
            return index
    return None


def _find_zone_end_line_index(
    lines: list[str],
    *,
    start: int,
    boundary: RegionBoundary,
) -> int | None:
    """Find the zone end boundary; unbounded end-regex zones are rejected."""
    if boundary.end is not None:
        return _find_end_index_by_marker(lines, start, len(lines), boundary.end)

    if boundary.end_regex is None:
        return None

    end_re = re.compile(boundary.end_regex)
    for index in range(start, len(lines)):
        if end_re.search(lines[index].strip()):
            return index
    return None


def find_bounded_regions_in_range(
    lines: list[str],
    start_index: int,
    end_index: int,
    boundary: RegionBoundary,
) -> list[tuple[int, int]]:
    """Return bounded regions fully contained between start_index and end_index."""
    regions: list[tuple[int, int]] = []
    search_start = start_index
    while search_start < end_index:
        region = find_bounded_region(
            lines,
            search_start,
            boundary,
            end_limit_exclusive=end_index,
        )
        if region is None or region[0] >= end_index or region[1] >= end_index:
            break
        regions.append(region)
        search_start = region[1] + 1
    return regions


def occurrence_key(boundary: RegionBoundary) -> tuple[str, str, str]:
    """Build a stable occurrence key for repeated bounded-region lookups."""
    return (
        boundary.start,
        boundary.end or '',
        boundary.end_regex or '',
    )


def _find_end_line_index(
    lines: list[str],
    *,
    start: int,
    boundary: RegionBoundary,
    end_limit_exclusive: int | None = None,
) -> int | None:
    """Return the end boundary index using literal `end` or `end_regex`."""
    limit = len(lines) if end_limit_exclusive is None else end_limit_exclusive
    if start >= limit:
        return None

    if boundary.end is not None:
        return _find_end_index_by_marker(lines, start, limit, boundary.end)

    if boundary.end_regex is None:
        return None

    return _find_end_index_by_regex(lines, start, limit, boundary.end_regex)


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
