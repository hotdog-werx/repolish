"""Contract tests for the summary row model: states, markers, row shapes.

The MARKERS table is exhaustive by contract: a state enum member added
without a marker must fail the suite, never render as a fallback glyph.
"""

from enum import Enum

import pytest

from repolish.reporting.rows import (
    MARKERS,
    STATE_ENUMS,
    CommandRow,
    CommandState,
    CopyRow,
    CopyState,
    FileRow,
    FileState,
    InsertionLine,
    InsertionState,
    PromotedRow,
    PromotedState,
    ProviderBranch,
    SessionGroup,
    SymlinkRow,
    ValidatorLine,
    ValidatorState,
    marker_for,
)


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


def test_rows_default_their_link_to_none() -> None:
    """Every row kind carries a link field so hyperlinks stay uniform."""
    assert FileRow(path='a.md', state=FileState.WRITTEN).link is None
    assert SymlinkRow(target='t', source='s').link is None
    assert CopyRow(target='t', source='s', state=CopyState.ACTIVE).link is None
    assert PromotedRow(path='p.md', state=PromotedState.WRITTEN).link is None
    assert ValidatorLine(name='lint', state=ValidatorState.PASS).link is None
    assert InsertionLine(state=InsertionState.OK, succeeded=1, failed=0).link is None
    assert ProviderBranch(alias='p').link is None
    assert SessionGroup(title='Standalone').link is None
    assert CommandRow(raw='true', state=CommandState.OK).link is None
