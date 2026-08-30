"""Standalone tests for the shared marker-driving primitives.

The feature-package tests (preprocessors, insertions) exercise these helpers
indirectly; these pin the helpers' contracts directly so a regression surfaces
in exactly one place.
"""

from pathlib import Path

from repolish.marker_kit import (
    OccurrenceTracker,
    RegionBoundary,
    apply_splices,
    find_all_bounded_regions,
    find_bounded_region,
    find_first_line_index,
    occurrence_key,
    pair_in_occurrence_order,
    read_text_or_none,
    write_mode_preserved,
)


def test_pair_in_occurrence_order_pairs_by_key_in_order() -> None:
    rendered = ['a1', 'b1', 'a2']
    local = ['a-L1', 'b-L1', 'a-L2']
    pairs = pair_in_occurrence_order(rendered, local, key=lambda s: s[0])
    assert pairs == [('a1', 'a-L1'), ('b1', 'b-L1'), ('a2', 'a-L2')]


def test_pair_in_occurrence_order_skips_missing_and_exhausted() -> None:
    rendered = ['x1', 'y1', 'x2']
    local = ['y-L1']  # no 'x' candidates at all
    pairs = pair_in_occurrence_order(rendered, local, key=lambda s: s[0])
    assert pairs == [('y1', 'y-L1')]

    # second 'x' when only one candidate exists
    pairs = pair_in_occurrence_order(['x1', 'x2'], ['x-L1'], key=lambda s: s[0])
    assert pairs == [('x1', 'x-L1')]


def test_occurrence_tracker_advances_offsets_per_key() -> None:
    tracker = OccurrenceTracker[str]()
    assert tracker.take('k', 2) == 0
    assert tracker.take('k', 3) == 2
    assert tracker.take('other', 1) == 0
    assert tracker.take('k', 0) == 5  # peek without advancing


def test_apply_splices_replaces_multiple_spans_offset_safely() -> None:
    text = 'alpha beta gamma delta'
    # replace 'beta' (6..10) and 'gamma' (11..16); longer replacements are safe
    result = apply_splices(text, [(6, 10, 'BETA-LONG'), (11, 16, 'Z')])
    assert result == 'alpha BETA-LONG Z delta'


def test_bounded_region_helpers_cover_literal_and_regex_bounds() -> None:
    lines = [
        'intro\n',
        '<!-- on -->\n',
        'body\n',
        '<!-- off -->\n',
        'outro\n',
    ]
    boundary = RegionBoundary(start='<!-- on -->', end='<!-- off -->')

    assert find_first_line_index(lines, 'body', start=0) == 2
    assert find_bounded_region(lines, 0, boundary) == (1, 3)
    assert find_all_bounded_regions(lines, boundary) == [(1, 3)]
    assert occurrence_key(boundary) == ('<!-- on -->', '<!-- off -->', '')

    regex_boundary = RegionBoundary(start='<!-- on -->', end_regex=r'^<!-- off')
    assert find_bounded_region(lines, 0, regex_boundary) == (1, 3)


def test_read_text_or_none_and_write_mode_preserved(tmp_path: Path) -> None:
    target = tmp_path / 'config.toml'
    assert read_text_or_none(target) is None  # missing -> None, never raises

    target.write_text('a = 1\n', encoding='utf-8')
    target.chmod(0o640)
    assert read_text_or_none(target) == 'a = 1\n'

    write_mode_preserved(target, 'a = 2\n')
    assert target.read_text(encoding='utf-8') == 'a = 2\n'
    assert (target.stat().st_mode & 0o777) == 0o640

    binary = tmp_path / 'blob.bin'
    binary.write_bytes(b'\xff\xfe\x00\x01')
    assert read_text_or_none(binary) is None
