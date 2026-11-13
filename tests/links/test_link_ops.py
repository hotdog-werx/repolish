"""Tests for the link-kind primitives shared by every link operation."""

import sys
from pathlib import Path

import pytest

from repolish.links.link_ops import (
    create_junction,
    is_junction,
    is_link,
    read_link_target,
    remove_link,
    supports_junctions,
)
from repolish.links.windows_utils import normalize_windows_path

_MOUNT_POINT_TAG = 0xA0000003
"""``IO_REPARSE_TAG_MOUNT_POINT``: the reparse tag a junction carries."""


class _JunctionStat:
    """lstat result stub carrying the junction reparse tag.

    ``st_mode`` is a directory mode because ``Path.is_symlink()`` reads
    ``os.lstat`` on Python 3.13+ (3.12 routes the same check through
    ``os.stat``): the stub stays a directory there too, never a link.
    """

    st_reparse_tag = _MOUNT_POINT_TAG
    st_mode = 0o040000  # S_IFDIR


def test_is_junction_is_false_for_everything_on_posix(tmp_path: Path) -> None:
    """POSIX has no reparse points: directories, files, and links are not junctions."""
    real_dir = tmp_path / 'dir'
    real_dir.mkdir()
    real_file = tmp_path / 'file.txt'
    real_file.write_text('x')
    link = tmp_path / 'link'
    link.symlink_to(real_dir, target_is_directory=True)

    assert not is_junction(real_dir)
    assert not is_junction(real_file)
    assert not is_junction(link)
    assert not is_junction(tmp_path / 'missing')


def test_is_junction_reads_the_mount_point_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A directory whose reparse tag is a mount point reports as a junction."""
    monkeypatch.setattr(
        'repolish.links.link_ops.os.lstat',
        lambda _path: _JunctionStat(),
    )
    assert is_junction(tmp_path)


def test_is_junction_reports_false_for_lstat_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable path is not a junction; the check never raises."""

    def _denied(_path: object) -> object:
        msg = 'denied'
        raise PermissionError(msg)

    monkeypatch.setattr('repolish.links.link_ops.os.lstat', _denied)
    assert not is_junction(tmp_path)


def test_is_link_spots_symlinks_and_junctions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anything a link run may leave behind reports as a link."""
    real_dir = tmp_path / 'dir'
    real_dir.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(real_dir, target_is_directory=True)

    assert is_link(link)
    assert not is_link(real_dir)

    monkeypatch.setattr(
        'repolish.links.link_ops.os.lstat',
        lambda _path: _JunctionStat(),
    )
    assert is_link(real_dir)


def test_read_link_target_reads_symlinks_without_following(tmp_path: Path) -> None:
    """A symlink reports the path it stores, not the resolved target.

    Windows stores the absolute target with its extended-length prefix,
    so both sides go through ``normalize_windows_path`` before comparing;
    the product compares the same way.
    """
    real_dir = tmp_path / 'dir'
    real_dir.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(real_dir, target_is_directory=True)

    assert normalize_windows_path(read_link_target(link)) == normalize_windows_path(real_dir)


def test_read_link_target_resolves_junctions(tmp_path: Path) -> None:
    """A junction has no readlink of its own: it resolves to its target.

    ``os.readlink`` raises ``ValueError`` on reparse points that are not
    symlinks (the stdlib's own ``realpath`` stops the same way), so the
    junction branch is the non-symlink read: it crosses the link through
    ``resolve()``.
    """
    real_dir = tmp_path / 'dir'
    real_dir.mkdir()

    assert read_link_target(real_dir) == real_dir.resolve()


def test_remove_link_unlinks_symlinks_only(tmp_path: Path) -> None:
    """Removing a symlink leaves the target untouched."""
    real_dir = tmp_path / 'dir'
    real_dir.mkdir()
    (real_dir / 'file.txt').write_text('data')
    link = tmp_path / 'link'
    link.symlink_to(real_dir, target_is_directory=True)

    remove_link(link)

    assert not link.is_symlink()
    assert (real_dir / 'file.txt').read_text() == 'data'


def test_remove_link_removes_junction_entries_with_rmdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A junction is removed with rmdir, which never follows into the target.

    ``shutil.rmtree`` sees a junction as a plain directory and would delete
    the target's contents; the entry itself is all that may go.
    """
    junction = tmp_path / 'junction'
    junction.mkdir()

    monkeypatch.setattr(
        'repolish.links.link_ops.os.lstat',
        lambda _path: _JunctionStat(),
    )
    remove_link(junction)

    assert not junction.exists()


def test_remove_link_ignores_plain_paths(tmp_path: Path) -> None:
    """A plain directory is not this function's to remove."""
    real_dir = tmp_path / 'dir'
    real_dir.mkdir()
    (real_dir / 'file.txt').write_text('data')

    remove_link(real_dir)

    assert (real_dir / 'file.txt').read_text() == 'data'


def test_supports_junctions_follows_the_platform() -> None:
    """Junctions are a Windows tier; POSIX reports them unsupported."""
    assert supports_junctions() is (sys.platform == 'win32')


def test_create_junction_refuses_when_junctions_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A platform that cannot serve junctions gets OSError: the copy signal.

    The gate is patched rather than skipped so the refusal runs on every
    platform, Windows included; the real platform matrix is covered by
    ``test_supports_junctions_follows_the_platform``.
    """
    monkeypatch.setattr(
        'repolish.links.link_ops.supports_junctions',
        lambda: False,
    )
    with pytest.raises(OSError, match='junctions exist on Windows only'):
        create_junction(tmp_path, tmp_path / 'junction')


def test_create_junction_passes_pointee_then_junction_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Windows helper receives (pointee, junction path) in that order.

    ``_winapi.CreateJunction`` takes the directory pointed at first and the
    junction being created second; the stub records the call so the order
    is pinned on POSIX too.
    """
    calls: list[tuple[str, str]] = []

    def _record(source: str, target: str) -> None:
        calls.append((source, target))

    monkeypatch.setattr(
        'repolish.links.link_ops.supports_junctions',
        lambda: True,
    )
    monkeypatch.setattr(
        'repolish.links.link_ops._winapi_create_junction',
        _record,
    )

    pointee = tmp_path / 'real'
    junction = tmp_path / 'junction'
    create_junction(pointee, junction)

    assert calls == [(str(pointee), str(junction))]
