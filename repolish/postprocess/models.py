"""Data records for a post-process run."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

OutcomeStatus = Literal['ok', 'failed', 'not_run']


@dataclass
class CommandOutcome:
    """One post-process command: what ran, and how it ended.

    *raw* keeps the user's argv with ``{placeholders}`` unsubstituted (what
    they wrote); *argv* holds the substituted form that executed.
    *placeholders* lists only the substitutions the command referenced.
    *status* is ``ok``, ``failed``, or ``not_run`` (commands after a failure
    are recorded but never started — the run stops at the first failure).
    *output* is the captured stdout+stderr (empty when verbosity streamed
    it live); *error* carries e.g. the missing-executable message.
    """

    raw: tuple[str, ...]
    argv: tuple[str, ...]
    placeholders: dict[str, str] = field(default_factory=dict)
    status: OutcomeStatus = 'ok'
    returncode: int | None = None
    duration_ms: int = 0
    output: str = ''
    error: str | None = None


@dataclass
class PostProcessRun:
    """The outcomes of one post-process invocation in *cwd*."""

    cwd: Path
    outcomes: list[CommandOutcome] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """Whether any command in the run failed."""
        return any(outcome.status == 'failed' for outcome in self.outcomes)
