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
    HookFailureState,
    InsertionState,
    LintState,
    PromotedState,
    ValidatorState,
)


@dataclass(frozen=True)
class Marker:
    """How a state renders: glyph prefix, rich style, and an optional note.

    The note renders after the path (`paused`, `(partially paused)`, the
    promoted-file annotations) in *note_style*, which differs from the
    glyph style for most states (`✗` yellow with a dim yellow note).

    `description` is the meaning of the state in plain words. It is the
    docs' source of truth: the local provider renders the summary-trees
    marker tables from this table, so a state without a description fails
    the suite instead of drifting from the documentation.
    """

    glyph: str
    style: str
    note: str = ''
    note_style: str | None = None
    description: str = ''

    @property
    def note_styled(self) -> str:
        """The rich style for the note; falls back to the glyph style."""
        return self.style if self.note_style is None else self.note_style


# Every member of every state enum, with its glyph and its description.
# Exhaustive by contract: tests assert each enum is fully covered and each
# description non-empty, so adding a state without a marker (or a marker
# without words) fails the suite instead of printing a wrong glyph or
# drifting from the documentation.
MARKERS: dict[Enum, Marker] = {
    FileState.WRITTEN: Marker(
        '✓ ',
        'green',
        description='The file was written to the project.',
    ),
    FileState.UNCHANGED: Marker(
        '~ ',
        'dim cyan',
        description='The project file already matched the rendered output.',
    ),
    FileState.DELETED: Marker(
        '✗ ',
        'dim red',
        description='A `delete` file mode removed the file.',
    ),
    FileState.DRIFT: Marker(
        '✗ ',
        'red',
        description=(
            'The project file differs from the rendered output. In check mode this is the state to watch for.'
        ),
    ),
    FileState.PAUSED: Marker(
        '✗ ',
        'yellow',
        'paused',
        'dim yellow',
        description=('A `paused_files` entry matched this file; repolish left it alone.'),
    ),
    FileState.SUPPRESSED: Marker(
        '✗ ',
        'yellow',
        'suppressed',
        'dim yellow',
        description='The template is suppressed via a `None` mapping.',
    ),
    FileState.DISABLED: Marker(
        '✗ ',
        'yellow',
        'disabled',
        'dim yellow',
        description='The template is disabled via config overrides.',
    ),
    FileState.ROOT_SKIPPED: Marker(
        '✗ ',
        'yellow',
        'not in create_file_mappings (root mode)',
        'dim yellow',
        description=(
            'In a monorepo root pass the file is not claimed by '
            '`create_file_mappings`, so it is never written to the root.'
        ),
    ),
    FileState.INSERTION_ONLY: Marker(
        '◌ ',
        'yellow',
        description=('Nothing was written for this file; the provider only manages insertion blocks inside it.'),
    ),
    FileState.VALIDATOR_ONLY: Marker(
        '◌ ',
        'yellow',
        description=('Nothing was written for this file; the provider only validates it.'),
    ),
    FileState.OK: Marker(
        '✓ ',
        'green',
        description=(
            'The file is clean: a row that carries validator lines beneath it, or a matching file in check mode.'
        ),
    ),
    CopyState.ACTIVE: Marker(
        '📋 ',
        'yellow',
        description='The resource copy was made.',
    ),
    CopyState.PAUSED: Marker(
        '⏸ ',
        'yellow',
        '(paused)',
        'dim yellow',
        description=('A `paused_files` entry matched the whole copy target; nothing was copied.'),
    ),
    CopyState.PARTIALLY_PAUSED: Marker(
        '◐ ',
        'yellow',
        '(partially paused)',
        'dim yellow',
        description=('A directory copy where some files inside it were held back by `paused_files`.'),
    ),
    PromotedState.WRITTEN: Marker(
        '↑ ',
        'green',
        '  promoted from {from_}',
        'dim',
        description='A member file was promoted and written to the root.',
    ),
    PromotedState.UNCHANGED: Marker(
        '~ ',
        'dim cyan',
        '  ↑ promoted from {from_}',
        'dim',
        description=('The promoted file already matched what the member session rendered.'),
    ),
    PromotedState.DIFFERS: Marker(
        '↑ ',
        'yellow',
        '  promoted from {from_} (differs)',
        'dim yellow',
        description=('The promoted file differs from what the member session rendered.'),
    ),
    PromotedState.OVERRIDDEN_BY_ROOT: Marker(
        '↑ ',
        'dim yellow',
        '  ⚠ overridden by {owner}',
        'dim yellow',
        description=('The root pass overrode the promoted file with its own template.'),
    ),
    PromotedState.PAUSED: Marker(
        '✗ ',
        'yellow',
        '  promoted from {from_} (paused)',
        'dim yellow',
        description=('A `paused_files` entry matched the promoted file, so it was left alone.'),
    ),
    PromotedState.SUPPRESSED: Marker(
        '✗ ',
        'yellow',
        '  promoted from {from_} (suppressed)',
        'dim yellow',
        description=('The promoted template is suppressed, so nothing was written for it.'),
    ),
    ValidatorState.PASS: Marker(
        '✓',
        'green',
        description=('The validator ran and passed. A pass shows only the validator name.'),
    ),
    ValidatorState.WARNING: Marker(
        '⚠',
        'yellow',
        description='The validator reported a warning, shown as `name: message`.',
    ),
    ValidatorState.ERROR: Marker(
        '✗',
        'red',
        description='The validator reported an error, shown as `name: message`.',
    ),
    ValidatorState.DISABLED: Marker(
        '✗',
        'yellow',
        description='The validator is disabled; the line reads `name: disabled`.',
    ),
    InsertionState.OK: Marker(
        '✓',
        'dim green',
        description='Every insertion block in the file landed.',
    ),
    InsertionState.FAILED: Marker(
        '✗',
        'yellow',
        description='At least one insertion block in the file failed to land.',
    ),
    CommandState.OK: Marker(
        '✓ ',
        'green',
        description='The post-process command exited 0.',
    ),
    CommandState.FAILED: Marker(
        '✗ ',
        'red',
        description=('The post-process command exited non-zero, showing the error message or exit code.'),
    ),
    CommandState.NOT_RUN: Marker(
        '✗ ',
        'yellow',
        description='The command was skipped because a previous one failed.',
    ),
    CommandState.SKIPPED: Marker(
        '- ',
        'dim',
        description=('The scoped command ran nothing: no generated files matched its `files` patterns.'),
    ),
    LintState.OK: Marker(
        '✓ ',
        'green',
        description='The template rendered cleanly with no findings.',
    ),
    LintState.FAILED: Marker(
        '✗ ',
        'red',
        description='The template failed to render or reported findings.',
    ),
    HookFailureState.FAILED: Marker(
        '✗ ',
        'red',
        description=(
            'A provider or facet hook raised and was skipped. The row '
            'reads `<hook> failed`, plus `(facet <name>)` for a facet '
            'hook, and the error message.'
        ),
    ),
}


def marker_for(state: Enum) -> Marker:
    """Return the marker for *state*; states without one fail loudly.

    The single lookup every renderer goes through. A KeyError here means a
    state enum member was added without a `MARKERS` entry: exactly the
    silent-green-checkmark bug class this module exists to prevent.
    """
    return MARKERS[state]
