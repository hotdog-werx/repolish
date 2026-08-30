"""File-level insertion driving: the node interface for target files.

Mirrors :mod:`repolish.preprocessors.files`: guarded read in, structured
result out, optional mode-preserving persist. Orchestration concerns —
provider attribution, per-provider reports, staged-tree layout — stay with
callers such as :mod:`repolish.commands.apply.insertions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hotlog import get_logger

from repolish.insertions.writer import write_back
from repolish.marker_kit import read_text_or_none, write_mode_preserved

if TYPE_CHECKING:
    from pathlib import Path

    from repolish.insertions.writer import RenderRegistry, WriteBackResult

logger = get_logger(__name__)


@dataclass(frozen=True)
class FileInsertionOutcome:
    """Outcome of rendering insertions over one file."""

    original: str
    result: WriteBackResult

    @property
    def changed(self) -> bool:
        """True when rendering altered the file's content."""
        return self.original != self.result.text


def render_insertions_file(
    path: Path,
    registry: RenderRegistry,
    *,
    file_path: str = '',
) -> FileInsertionOutcome | None:
    """Read *path* and render its insertion blocks against *registry*.

    Pure with respect to the filesystem — the file is read but never written.
    Returns ``None`` when the file is unreadable or not valid UTF-8.
    ``file_path`` annotates blocks/diagnostics; pass the file's project-relative
    path when known.
    """
    text = read_text_or_none(path)
    if text is None:
        logger.debug('insertions_unreadable_file', path=str(path))
        return None
    return FileInsertionOutcome(
        original=text,
        result=write_back(text, registry, file_path=file_path),
    )


def apply_insertions_file(
    path: Path,
    registry: RenderRegistry,
    *,
    file_path: str = '',
) -> FileInsertionOutcome | None:
    """Render insertions for *path* and persist only when content changed.

    Returns the same outcome as :func:`render_insertions_file`; ``None`` when
    unreadable.
    """
    outcome = render_insertions_file(path, registry, file_path=file_path)
    if outcome is not None and outcome.changed:
        write_mode_preserved(path, outcome.result.text)
    return outcome
