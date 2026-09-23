"""The terminal renderer's glyph table: how each summary state draws.

MARKERS is an implementation detail of the terminal tree (an HTML
renderer would map the same states its own way), but its exhaustiveness
is load-bearing: tests assert each state enum in `repolish.summaries` is
fully covered, so adding a state without a marker fails the suite instead
of printing a wrong glyph.
"""

from dataclasses import dataclass
from enum import Enum

from repolish.summaries.rows import (
    CommandState,
    CopyState,
    FileState,
    InsertionState,
    PromotedState,
    ValidatorState,
)


@dataclass(frozen=True)
class Marker:
    """How a state renders: glyph prefix, rich style, and an optional note.

    The note renders after the path (`paused`, `(partially paused)`, the
    promoted-file annotations) in *note_style*, which differs from the
    glyph style for most states (`✗` yellow with a dim yellow note).
    """

    glyph: str
    style: str
    note: str = ''
    note_style: str | None = None

    @property
    def note_styled(self) -> str:
        """The rich style for the note; falls back to the glyph style."""
        return self.style if self.note_style is None else self.note_style


# Every member of every state enum, with its glyph. Exhaustive by contract:
# tests assert each enum is fully covered, so adding a state without a
# marker fails the suite instead of printing a wrong glyph.
MARKERS: dict[Enum, Marker] = {
    FileState.WRITTEN: Marker('✓ ', 'green'),
    FileState.UNCHANGED: Marker('~ ', 'dim cyan'),
    FileState.DELETED: Marker('✗ ', 'dim red'),
    FileState.DRIFT: Marker('✗ ', 'red'),
    FileState.PAUSED: Marker('✗ ', 'yellow', 'paused', 'dim yellow'),
    FileState.SUPPRESSED: Marker('✗ ', 'yellow', 'suppressed', 'dim yellow'),
    FileState.DISABLED: Marker('✗ ', 'yellow', 'disabled', 'dim yellow'),
    FileState.ROOT_SKIPPED: Marker(
        '✗ ',
        'yellow',
        'not in create_file_mappings (root mode)',
        'dim yellow',
    ),
    FileState.INSERTION_ONLY: Marker('◌ ', 'yellow'),
    FileState.VALIDATOR_ONLY: Marker('◌ ', 'yellow'),
    FileState.OK: Marker('✓ ', 'green'),
    CopyState.ACTIVE: Marker('📋 ', 'yellow'),
    CopyState.PAUSED: Marker('⏸ ', 'yellow', '(paused)', 'dim yellow'),
    CopyState.PARTIALLY_PAUSED: Marker(
        '◐ ',
        'yellow',
        '(partially paused)',
        'dim yellow',
    ),
    PromotedState.WRITTEN: Marker(
        '↑ ',
        'green',
        '  promoted from {from_}',
        'dim',
    ),
    PromotedState.UNCHANGED: Marker(
        '~ ',
        'dim cyan',
        '  ↑ promoted from {from_}',
        'dim',
    ),
    PromotedState.DIFFERS: Marker(
        '↑ ',
        'yellow',
        '  promoted from {from_} (differs)',
        'dim yellow',
    ),
    PromotedState.OVERRIDDEN_BY_ROOT: Marker(
        '↑ ',
        'dim yellow',
        '  ⚠ overridden by {owner}',
        'dim yellow',
    ),
    PromotedState.PAUSED: Marker(
        '✗ ',
        'yellow',
        '  promoted from {from_} (paused)',
        'dim yellow',
    ),
    PromotedState.SUPPRESSED: Marker(
        '✗ ',
        'yellow',
        '  promoted from {from_} (suppressed)',
        'dim yellow',
    ),
    ValidatorState.PASS: Marker('✓', 'green'),
    ValidatorState.WARNING: Marker('⚠', 'yellow'),
    ValidatorState.ERROR: Marker('✗', 'red'),
    ValidatorState.DISABLED: Marker('✗', 'yellow'),
    InsertionState.OK: Marker('✓', 'dim green'),
    InsertionState.FAILED: Marker('✗', 'yellow'),
    CommandState.OK: Marker('✓ ', 'green'),
    CommandState.FAILED: Marker('✗ ', 'red'),
    CommandState.NOT_RUN: Marker('✗ ', 'yellow'),
}


def marker_for(state: Enum) -> Marker:
    """Return the marker for *state*; states without one fail loudly.

    The single lookup every renderer goes through. A KeyError here means a
    state enum member was added without a `MARKERS` entry: exactly the
    silent-green-checkmark bug class this module exists to prevent.
    """
    return MARKERS[state]
