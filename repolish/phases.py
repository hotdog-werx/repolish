"""Coarse execution-phase timing.

A `PhaseTimer` names the phases of a run (config load, render, post-process,
...) and records how long each took. The durations surface as structured
hotlog debug events and a text section in the post-process report —
groundwork for finding slow areas later; default display does not change.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from hotlog import get_logger

logger = get_logger(__name__)


def _fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f'{ms / 1000:.1f}s'
    return f'{ms:.0f}ms'


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

    def emit(self) -> None:
        """Emit one structured debug event per recorded phase."""
        for name, ms in self._durations.items():
            logger.debug('phase_completed', phase=name, ms=int(ms))

    def section(self) -> str:
        """Render the durations as a `render 183ms · post-process 1.4s` section."""
        return ' · '.join(f'{name.replace("_", "-")} {_fmt_ms(ms)}' for name, ms in self._durations.items())
