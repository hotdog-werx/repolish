"""Link-kind primitives for the symlink, junction, copy chain.

A linked path in a repolish project is one of three kinds: a real symlink,
a Windows junction directory, or a plain copy. POSIX only ever produces
symlinks and copies. Windows prefers a real symlink (needs developer mode
or an elevated console), falls back to a junction (no privilege required,
local volumes only, which is exactly the contract repolish links need),
and uses a copy as the last resort.

Every check that used to read ``path.is_symlink()`` must go through
:func:`is_link` here, and every removal of a possibly-linked path must go
through :func:`remove_link`. A junction reports as a plain directory to
``Path.is_symlink()`` and ``shutil.rmtree()`` follows it into the target,
so an unchecked removal deletes the *target's* contents, which for a
repolish link is the provider package itself.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

LinkKind = Literal['symlink', 'junction', 'copy']
"""How a target was materialised. Shows up in link logs and summaries."""

_MOUNT_POINT_TAG = 0xA0000003
"""``IO_REPARSE_TAG_MOUNT_POINT``: the reparse tag a junction carries.

The stdlib only exposes the tag constants on Windows builds, so the
value is spelled out here to keep the check portable."""


def is_junction(path: Path) -> bool:
    """True when *path* is a Windows junction directory (never on POSIX).

    Mirrors the stdlib's ``os.path.isjunction`` without requiring 3.12: a
    junction is a reparse point tagged as a mount point. Symlinks carry a
    different tag, so they report as links, not junctions.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(st, 'st_reparse_tag', 0) == _MOUNT_POINT_TAG)


def is_link(path: Path) -> bool:
    """True when *path* is a symlink or a junction, whatever it points at.

    The one check every linked-path decision must use: dangling links
    report as absent to ``Path.exists()`` and junctions report as plain
    directories, so without this both kinds hide from the caller.
    """
    return path.is_symlink() or is_junction(path)


def read_link_target(path: Path) -> Path:
    """Return the path a link points at, without following it.

    Symlinks read through ``Path.readlink()``. Junctions are not symlinks:
    ``os.readlink`` raises ``ValueError`` on them (the stdlib's own
    ``realpath`` stops at reparse points that are not symlinks), so they
    resolve instead. ``resolve()`` crosses the junction to the real
    target, which is what every consumer compares against its expected
    source.
    """
    if path.is_symlink():
        return path.readlink()
    return path.resolve()


def remove_link(path: Path) -> None:
    """Remove a symlink or junction without touching anything it points at.

    A junction is removed with ``Path.rmdir``, which deletes the reparse
    point entry only. ``Path.unlink()`` cannot remove it, and
    ``shutil.rmtree()`` would follow it and delete the target's contents.
    """
    if path.is_symlink():
        path.unlink()
    elif is_junction(path):
        path.rmdir()


def supports_junctions() -> bool:
    """True on Windows, where junction directories exist."""
    return sys.platform == 'win32'


def _winapi_create_junction(source: str, target: str) -> None:  # pragma: no cover - Windows-only
    """Create the junction through CPython's private ``_winapi`` helper.

    The indirection keeps :func:`create_junction` testable on POSIX: the
    platform gate is the only branch that has to run anywhere else.
    """
    import _winapi  # noqa: PLC0415 - a Windows-only extension module

    _winapi.CreateJunction(source, target)


def create_junction(source: Path, target: Path) -> None:
    """Create a Windows junction at *target* pointing at *source*.

    Raises ``OSError`` when junctions are unavailable (POSIX, or a
    filesystem without reparse points); callers treat that as the signal
    to fall back to a copy.
    """
    if not supports_junctions():
        msg = 'junctions exist on Windows only'
        raise OSError(msg)
    _winapi_create_junction(str(source), str(target))
