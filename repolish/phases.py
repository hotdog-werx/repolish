"""Coarse execution-phase timing.

A `PhaseTimer` names the phases of a run (config load, render, post-process,
...) and records how long each took. The durations surface as structured
hotlog debug events and as a JSON file (`.repolish/_/phase-timings.json`)
linked from the `completed in ...` footer of apply/check runs — groundwork
for finding slow areas later; default display adds only that one footer
line.
"""

import json
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from hotlog import get_logger

logger = get_logger(__name__)


class PhaseTimer:
    """Record named execution-phase durations for one session."""

    def __init__(self) -> None:
        self._durations: dict[str, float] = {}

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Time the block under *name* (repeat names accumulate)."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.record(name, (time.perf_counter() - start) * 1000)

    def record(self, name: str, ms: float) -> None:
        """Add *ms* to phase *name* (creating it on first record)."""
        self._durations[name] = self._durations.get(name, 0.0) + ms

    @property
    def durations(self) -> dict[str, float]:
        """Recorded phase durations in ms, keyed by phase name."""
        return dict(self._durations)

    def emit(self) -> None:
        """Emit one structured debug event per recorded phase."""
        for name, ms in self._durations.items():
            logger.debug('phase_completed', phase=name, ms=int(ms))


def write_phase_timings(
    path: Path,
    total_ms: float,
    sessions: Sequence[tuple[str, PhaseTimer]],
) -> Path:
    """Write per-session phase durations as JSON to *path* (parents created).

    *sessions* pairs each session's display name with its timer; *total_ms*
    is the wall time of the whole command, measured by the caller.
    """
    payload = {
        'total_ms': round(total_ms),
        'sessions': [
            {
                'name': name,
                'phases': {phase: round(ms) for phase, ms in timer.durations.items()},
            }
            for name, timer in sessions
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path
