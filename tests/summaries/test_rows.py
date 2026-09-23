"""Contract tests for the summary row model: states and row shapes.

Adding a state enum member is a deliberate act recorded in `STATE_ENUMS`
(the marker exhaustiveness tests live in `tests/reporting/test_markers.py`).
"""

from repolish.summaries.rows import (
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
)


def test_state_enums_lists_every_state_enum() -> None:
    names = [enum_cls.__name__ for enum_cls in STATE_ENUMS]
    assert names == [
        'FileState',
        'CopyState',
        'PromotedState',
        'ValidatorState',
        'InsertionState',
        'CommandState',
    ]


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
