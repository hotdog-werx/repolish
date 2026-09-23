"""The summary-tree row model: typed states, markers, and row dataclasses.

The contract between summary derivation and summary rendering. Producers
(`repolish.reporting.apply_rows`, `repolish.reporting.post_process`) turn
session state into the rows defined here; leaf renderers
(`repolish.reporting.leaves`) turn rows into `SummaryNode` trees. Neither
side invents markers or status strings: every glyph a summary can print
comes from `MARKERS`, one exhaustive table keyed by the state enums, so a
new state cannot silently render as a green check mark.

Rows are plain data. They carry no rich objects and no session references;
`link` fields hold the paths the row hyperlinks to (file-context debug JSON,
validator reports, post-process reports) so every row kind gets the same
`[details]` treatment.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FileState(Enum):
    """What happened to one provider-managed file in this run."""

    WRITTEN = 'written'
    UNCHANGED = 'unchanged'
    DELETED = 'deleted'
    DRIFT = 'drift'
    PAUSED = 'paused'
    SUPPRESSED = 'suppressed'
    DISABLED = 'disabled'
    ROOT_SKIPPED = 'not in create_file_mappings (root mode)'
    INSERTION_ONLY = 'insertion only'
    VALIDATOR_ONLY = 'validator only'
    OK = 'ok'


class CopyState(Enum):
    """What happened to one provider resource copy in this run."""

    ACTIVE = 'active'
    PAUSED = 'paused'
    PARTIALLY_PAUSED = 'partially paused'


class PromotedState(Enum):
    """What happened to one member file promoted to the repo root."""

    WRITTEN = 'written'
    UNCHANGED = 'unchanged'
    DIFFERS = 'differs'
    OVERRIDDEN_BY_ROOT = 'overridden_by_root'
    PAUSED = 'paused'
    SUPPRESSED = 'suppressed'


class ValidatorState(Enum):
    """The outcome of one validator execution on one file.

    The session records only non-PASS outcomes (`validation_results` holds
    warnings and errors), so an absent result is a PASS, never an unknown.
    """

    PASS = 'pass'  # noqa: S105 - a pass status, not a hardcoded password
    WARNING = 'warning'
    ERROR = 'error'
    DISABLED = 'disabled'


class InsertionState(Enum):
    """The outcome of one file's insertion blocks."""

    OK = 'ok'
    FAILED = 'failed'


class CommandState(Enum):
    """The outcome of one post-process command."""

    OK = 'ok'
    FAILED = 'failed'
    NOT_RUN = 'not_run'


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


@dataclass(frozen=True)
class ValidatorLine:
    """One validator entry beneath a file row."""

    name: str
    state: ValidatorState
    message: str = ''
    link: Path | None = None


@dataclass(frozen=True)
class InsertionLine:
    """The insertion-block outcome line beneath a file row."""

    state: InsertionState
    succeeded: int
    failed: int
    disabled: int = 0
    link: Path | None = None


@dataclass(frozen=True)
class FileRow:
    """One provider-managed file in the apply summary tree."""

    path: str
    state: FileState
    source: str = ''
    mode_note: str = ''
    owner_note: str = ''
    validators: tuple[ValidatorLine, ...] = ()
    insertion: InsertionLine | None = None
    validator_report: Path | None = None
    link: Path | None = None


@dataclass(frozen=True)
class SymlinkRow:
    """One provider symlink in the apply summary tree."""

    target: str
    source: str
    link: Path | None = None


@dataclass(frozen=True)
class CopyRow:
    """One provider resource copy in the apply summary tree."""

    target: str
    source: str
    state: CopyState
    link: Path | None = None


@dataclass(frozen=True)
class PromotedRow:
    """One member file promoted to the repo root."""

    path: str
    state: PromotedState
    promoted_from: str = ''
    overridden_by: str = ''
    link: Path | None = None


@dataclass(frozen=True)
class AppliedStats:
    """Post-apply provider counts appended to a provider branch label."""

    written: int = 0
    unchanged: int = 0
    deleted: int = 0
    drift: int = 0
    skipped: int = 0
    symlinks: int = 0
    copies: int = 0


@dataclass(frozen=True)
class PendingStats:
    """Pre-apply provider counts appended to a provider branch label."""

    applied: int
    not_applied: int
    copies: int = 0


@dataclass(frozen=True)
class ProviderBranch:
    """One provider's branch in the apply summary tree."""

    alias: str
    version: str | None = None
    rows: tuple[FileRow | SymlinkRow | CopyRow, ...] = ()
    stats: AppliedStats | PendingStats | None = None
    link: Path | None = None


@dataclass(frozen=True)
class SessionGroup:
    """One role group (Root / Member / Standalone) of the apply summary."""

    title: str
    branches: tuple[ProviderBranch, ...] = ()
    promoted: tuple[PromotedRow, ...] = ()
    link: Path | None = None


@dataclass(frozen=True)
class CommandRow:
    """One post-process command in the post-process summary tree."""

    raw: str
    state: CommandState
    duration_ms: int = 0
    error: str | None = None
    returncode: int | None = None
    link: Path | None = None


@dataclass(frozen=True)
class PostProcessGroup:
    """One session's post-process commands, sharing one report file.

    Runs with their own report (a promoted-files pass) nest as subgroups
    with a link of their own. `ok`/`failed`/`not_run` carry the counts the
    group label appends; subgroups count their own rows.
    """

    label: str
    link: Path | None = None
    commands: tuple[CommandRow, ...] = ()
    subgroups: tuple['PostProcessGroup', ...] = ()
    ok: int = 0
    failed: int = 0
    not_run: int = 0


STATE_ENUMS: tuple[type[Enum], ...] = (
    FileState,
    CopyState,
    PromotedState,
    ValidatorState,
    InsertionState,
    CommandState,
)
"""Every state enum, in declaration order; tests assert marker coverage."""
