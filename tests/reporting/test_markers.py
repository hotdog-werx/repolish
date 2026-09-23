"""Contract tests for the terminal marker table.

The MARKERS table is exhaustive by contract: a state enum member added
without a marker must fail the suite, never render as a fallback glyph.
"""

from enum import Enum

import pytest

from repolish.reporting.markers import MARKERS, marker_for
from repolish.summaries import STATE_ENUMS
from repolish.summaries.rows import FileState


def test_every_state_member_has_a_marker() -> None:
    for enum_cls in STATE_ENUMS:
        for member in enum_cls:
            assert member in MARKERS, f'{enum_cls.__name__}.{member.name} has no marker'


def test_markers_table_covers_exactly_the_state_enums() -> None:
    known = {member for enum_cls in STATE_ENUMS for member in enum_cls}
    assert set(MARKERS) == known


def test_every_marker_has_a_glyph() -> None:
    for state, marker in MARKERS.items():
        assert marker.glyph, f'{state!r} has an empty glyph'


def test_marker_for_unknown_state_fails_loudly() -> None:
    """A state without a marker raises instead of rendering a fallback glyph."""

    class Untracked(Enum):
        NEW = 'new'

    with pytest.raises(KeyError):
        marker_for(Untracked.NEW)


def test_marker_note_style_defaults_to_glyph_style() -> None:
    assert MARKERS[FileState.PAUSED].note_styled == 'dim yellow'
    assert MARKERS[FileState.WRITTEN].note_styled == 'green'
