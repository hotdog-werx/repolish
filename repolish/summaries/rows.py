"""The summary row model: typed states and row dataclasses.

The output contract of `repolish.summaries`. Derivation
(`repolish.summaries.apply_rows`, `repolish.summaries.post_process`) turns
the finished session's state into the rows defined here; a renderer
(`repolish.reporting.leaves` today, an HTML renderer later) turns rows into
its own output. A summary is just a state: no glyphs, styles, or other
display decisions live here, and adding a state is a deliberate act
recorded in `STATE_ENUMS` (renderers keep exhaustive tables keyed by it,
so a new state fails loudly instead of rendering as a green check mark).

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
