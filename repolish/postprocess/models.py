"""Data records for a post-process run, and the scoped entry model."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

OutcomeStatus = Literal['ok', 'failed', 'not_run', 'skipped']


class PostProcessEntry(BaseModel):
    """A scoped ``post_process`` command from ``repolish.yaml``.

    The mapping form exists to declare a file scope; a plain string entry
    covers the always-run case. ``files`` uses the shared path-entry
    pattern language (exact path, directory, or ``fnmatch`` glob — see
    :func:`repolish.misc.path_entry_matches`): the command runs only when
    the run generated a file matching one of the entries, and is recorded
    as ``skipped`` otherwise. Required and non-empty — the mapping form
    has no other purpose, so an absent or empty scope is a config error,
    not a silent no-op.
    """

    command: str | list[str] = Field(
        description='The command to run (string or argv list).',
    )
    files: list[str] = Field(
        min_length=1,
        description='Path entries that must match a generated file to trigger the command.',
    )


@dataclass
class CommandOutcome:
    """One post-process command: what ran, and how it ended.

    *raw* keeps the user's argv with ``{placeholders}`` unsubstituted (what
    they wrote); *argv* holds the substituted form that executed.
    *placeholders* lists only the substitutions the command referenced.
    *status* is ``ok``, ``failed``, ``not_run`` (commands after a failure
    are recorded but never started — the run stops at the first failure),
    or ``skipped`` (a scoped command whose ``files`` matched nothing the
    run generated). *output* is the captured stdout+stderr (empty when
    verbosity streamed it live); *error* carries e.g. the
    missing-executable message. *scope* is the entry's ``files`` patterns,
    set only on scoped entries.
    """

    raw: tuple[str, ...]
    argv: tuple[str, ...]
    placeholders: dict[str, str] = field(default_factory=dict)
    status: OutcomeStatus = 'ok'
    returncode: int | None = None
    duration_ms: int = 0
    output: str = ''
    error: str | None = None
    scope: tuple[str, ...] | None = None


@dataclass
class PostProcessRun:
    """The outcomes of one post-process invocation in *cwd*."""

    cwd: Path
    outcomes: list[CommandOutcome] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """Whether any command in the run failed."""
        return any(outcome.status == 'failed' for outcome in self.outcomes)
