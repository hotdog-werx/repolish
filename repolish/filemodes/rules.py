"""FileMode semantics: the one place that decides what a mode allows.

The enum declares a destination's disposition; :class:`ModeRules` folds a
session's declarations into the decisions every writer and checker must
honor. Before this package existed, each writer re-derived ``is this file
developer-owned`` on its own, and a new writer path (#100's insertion
staging) could silently miss the create-only rule and overwrite a
developer's file. Now the rule lives here: a writer asks
:meth:`ModeRules.can_write`, a checker asks
:meth:`ModeRules.excluded_from_check`, and no consumer knows how the
answer is computed.

Accumulation is shared too: :func:`fold_mapping` is the single table from
``FileMode`` to destination-set claims, used by both the provider
collection path and the fast-lane transforms (which adapt their lists via
the :class:`ModeSet` protocol).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from repolish.hydration.mapping_resolution import MappingResolution
    from repolish.providers import SessionBundle


class FileMode(str, Enum):
    """Per-file behavior for a `TemplateMapping`.

    - REGULAR: render and materialize as normal (default)
    - CREATE_ONLY: treat the destination as create-only (never overwrite existing)
    - DELETE: mark the destination for deletion (no source template required)
    - KEEP: explicitly cancel a delete scheduled by an earlier provider
    - SUPPRESS: skip staging and rendering for this file entirely; useful
      during development when a template is temporarily broken
    """

    REGULAR = 'regular'
    CREATE_ONLY = 'create_only'
    DELETE = 'delete'
    KEEP = 'keep'
    SUPPRESS = 'suppress'


MATERIALIZED_MODES: tuple[FileMode, FileMode] = (
    FileMode.REGULAR,
    FileMode.CREATE_ONLY,
)
"""Modes whose files are rendered and written; the rest are bookkeeping only."""


def posix_dests(paths: Iterable[Path]) -> frozenset[str]:
    """Return the POSIX string form of every destination path."""
    return frozenset(path.as_posix() for path in paths)


class ModeSet(Protocol):
    """Mutable destination collection: a set, or a list adapter.

    Parameters are positional-only so ``set[Path]`` satisfies the protocol
    (``set.add`` takes its element positionally).
    """

    def add(self, path: Path, /) -> None:
        """Claim the path for the collection."""
        ...

    def discard(self, path: Path, /) -> None:
        """Cancel an earlier claim of the path."""
        ...


def fold_mapping(
    mode: FileMode,
    path: Path,
    *,
    create_only: ModeSet,
    delete: ModeSet,
) -> None:
    """Fold one mapping's mode claim into the accumulating destination sets.

    DELETE claims the path for deletion, KEEP cancels an earlier delete,
    CREATE_ONLY claims it as create-only. REGULAR and SUPPRESS make no
    claim: their behavior lives with the mapping dictionaries, not the
    destination sets.
    """
    if mode is FileMode.DELETE:
        delete.add(path)
    elif mode is FileMode.KEEP:
        delete.discard(path)
    elif mode is FileMode.CREATE_ONLY:
        create_only.add(path)


@dataclass(frozen=True)
class ModeRules:
    """The mode decisions for one session, in POSIX destination form.

    Every writer and checker asks this object instead of re-deriving the
    rules from the bundle: insertions, the mapping copy pass, and the
    drift checks all share the same answers, so a new writer path cannot
    invent its own.
    """

    create_only: frozenset[str]
    delete: frozenset[str]

    @classmethod
    def from_bundle(cls, providers: SessionBundle) -> ModeRules:
        """Rules for a session bundle (callers without a MappingResolution)."""
        return cls(
            posix_dests(providers.create_only_files),
            posix_dests(providers.delete_files),
        )

    @classmethod
    def from_resolution(cls, resolution: MappingResolution) -> ModeRules:
        """Rules from the normalized hydration view (no recompute)."""
        return cls(
            frozenset(resolution.create_only_dests),
            frozenset(resolution.delete_dests),
        )

    def can_write(self, rel_path: str, base_dir: Path) -> bool:
        """Return False only for a create-only destination that already exists.

        A create-only file is developer-owned from the moment it exists:
        repolish created it once and must never touch it again. Any pass
        that writes to the project tree asks this first.
        """
        return rel_path not in self.create_only or not (base_dir / rel_path).exists()

    def excluded_from_check(self, rel_path: str, base_dir: Path) -> bool:
        """Return True when check mode must ignore drift on this path.

        Delete-destined paths are about to disappear, and an existing
        create-only destination is developer-owned: neither may report
        diffs.
        """
        return rel_path in self.delete or not self.can_write(rel_path, base_dir)

    def existing_create_only(self, base_dir: Path) -> frozenset[str]:
        """Return the create-only destinations that already exist."""
        return frozenset(rel_path for rel_path in self.create_only if (base_dir / rel_path).exists())
