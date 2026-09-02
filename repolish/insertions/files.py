"""File-level insertion driving: the node interface for target files.

Mirrors :mod:`repolish.directives.files`: guarded read in, structured
result out, optional mode-preserving persist. Orchestration concerns —
provider attribution, per-provider reports, staged-tree layout — stay with
callers such as :mod:`repolish.commands.apply.insertions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hotlog import get_logger

from repolish.insertions.writer import WriteBackResult, write_back
from repolish.insertions.zones import fill_insert_zones
from repolish.marker_kit import read_text_or_none, write_mode_preserved

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from repolish.directives import InsertZoneDeclaration
    from repolish.insertions.models import InsertionBlock
    from repolish.insertions.writer import RenderRegistry

logger = get_logger(__name__)


@dataclass(frozen=True)
class FileInsertionOutcome:
    """Outcome of rendering insertions (and zones) over one file."""

    original: str
    result: WriteBackResult
    zone_blocks: tuple[InsertionBlock, ...] = ()
    """Synthetic blocks for filled insertion zones, for provider attribution
    and disabled-override reporting alongside the parsed ones."""

    @property
    def changed(self) -> bool:
        """True when rendering altered the file's content."""
        return self.original != self.result.text


def render_insertions_text(
    text: str,
    registry: RenderRegistry,
    *,
    file_path: str = '',
    zone_declarations: Iterable[InsertZoneDeclaration] = (),
    zone_registry: RenderRegistry | None = None,
) -> tuple[WriteBackResult, tuple[InsertionBlock, ...]]:
    """Render ``repolish:on`` blocks and zone declarations over *text*.

    ``write_back`` runs first; the zone fill then operates on its output.
    Diagnostics, block counts, and function names merge into one
    :class:`WriteBackResult`; the zones' synthetic blocks ride back alongside
    so callers can attribute failures to providers the same way they do for
    ``repolish:on`` blocks.

    ``registry`` is the file's allowlist for developer-authored markers.
    ``zone_registry`` (defaults to ``registry``) resolves zone fills — zones
    are provider-authored, so callers pass the session-wide registry.
    """
    back = write_back(text, registry, file_path=file_path)
    zones = fill_insert_zones(
        back.text,
        zone_declarations,
        registry if zone_registry is None else zone_registry,
        file_path=file_path,
    )
    result = WriteBackResult(
        text=zones.text,
        diagnostics=[*back.diagnostics, *zones.diagnostics],
        total_blocks=back.total_blocks + zones.total_blocks,
        failed_blocks=back.failed_blocks + zones.failed_blocks,
        functions=(*back.functions, *zones.functions),
    )
    return result, tuple(zones.blocks)


def render_insertions_file(
    path: Path,
    registry: RenderRegistry,
    *,
    file_path: str = '',
    zone_declarations: Iterable[InsertZoneDeclaration] = (),
    zone_registry: RenderRegistry | None = None,
) -> FileInsertionOutcome | None:
    """Read *path* and render its insertion blocks against *registry*.

    Pure with respect to the filesystem — the file is read but never written.
    Returns ``None`` when the file is unreadable or not valid UTF-8.
    ``file_path`` annotates blocks/diagnostics; pass the file's project-relative
    path when known. ``zone_registry`` selects the registry zone fills resolve
    against (defaults to *registry*).
    """
    text = read_text_or_none(path)
    if text is None:
        logger.debug('insertions_unreadable_file', path=str(path))
        return None
    result, zone_blocks = render_insertions_text(
        text,
        registry,
        file_path=file_path,
        zone_declarations=zone_declarations,
        zone_registry=zone_registry,
    )
    return FileInsertionOutcome(
        original=text,
        result=result,
        zone_blocks=zone_blocks,
    )


def apply_insertions_file(
    path: Path,
    registry: RenderRegistry,
    *,
    file_path: str = '',
    zone_declarations: Iterable[InsertZoneDeclaration] = (),
    zone_registry: RenderRegistry | None = None,
) -> FileInsertionOutcome | None:
    """Render insertions for *path* and persist only when content changed.

    Returns the same outcome as :func:`render_insertions_file`; ``None`` when
    unreadable. ``zone_registry`` selects the registry zone fills resolve
    against (defaults to *registry*).
    """
    outcome = render_insertions_file(
        path,
        registry,
        file_path=file_path,
        zone_declarations=zone_declarations,
        zone_registry=zone_registry,
    )
    if outcome is not None and outcome.changed:
        write_mode_preserved(path, outcome.result.text)
    return outcome
