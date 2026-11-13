"""Tests for the console factory and output helpers every render goes through."""

import io
from pathlib import Path

from pytest_mock import MockerFixture

from repolish.console import build_console, ensure_utf8_output, hyperlink_style


class _NoReconfigure:
    """A capture wrapper with an encoding but no ``reconfigure``."""

    encoding = 'ascii'


class _BrokenReconfigure:
    """A stream whose reconfigure fails; entry must survive anything."""

    encoding = 'ascii'

    def reconfigure(self, **kwargs: str) -> None:
        msg = 'boom'
        raise OSError(msg)


def test_build_console_never_uses_the_legacy_windows_renderer(
    mocker: MockerFixture,
) -> None:
    """Rich's legacy renderer dies on piped std streams; the factory opts out.

    The flag is pinned through a spy on the constructor rather than the
    ``legacy_windows`` property: every CI leg reports the property as
    False, but only the constructor argument holds on a machine where
    Rich's probe would pick the legacy renderer.
    """
    spy = mocker.patch('repolish.console.Console')
    build_console(force_terminal=True)
    spy.assert_called_once_with(legacy_windows=False, force_terminal=True)


def test_hyperlink_style_composes_the_uri_with_as_uri(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """Hand-rolled ``file://{path}`` hrefs put a Windows drive in the host slot.

    ``as_uri()`` keeps the drive in the path (`file:///C:/...`) and
    percent-encodes spaces; the style is pinned to it so POSIX (where
    the two forms coincide for simple paths) and Windows open the same
    correct target.
    """
    mocker.patch('repolish.console.supports_hyperlinks', new=True)
    spaced = tmp_path / 'my dir' / 'a b.txt'
    spaced.parent.mkdir()

    assert hyperlink_style(spaced) == f'link {spaced.absolute().as_uri()}'
    assert '%20' in hyperlink_style(spaced)


def test_hyperlink_style_returns_the_prefix_when_links_are_off(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    """No hyperlinks, or no path: the label keeps its own styling."""
    mocker.patch('repolish.console.supports_hyperlinks', new=False)

    assert hyperlink_style(tmp_path, 'bold') == 'bold'
    assert hyperlink_style(None, 'bold') == 'bold'
    assert hyperlink_style(None) == ''


def test_ensure_utf8_output_reconfigures_non_utf8_streams_in_place(
    mocker: MockerFixture,
) -> None:
    """A cp1252 pipe is the crash; the same stream object re-speaks utf-8.

    The glyph write proves the fix works for writers that already hold
    the stream (rich's console, hotlog's): reconfigure mutates in place.
    """
    piped = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
    already_utf8 = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
    mocker.patch('sys.stdout', new=piped)
    mocker.patch('sys.stderr', new=already_utf8)

    ensure_utf8_output()

    assert piped.encoding == 'utf-8'
    assert piped.errors == 'replace'
    assert already_utf8.encoding == 'utf-8'
    piped.write('✓ ← 📋')
    piped.flush()
    assert b'\xe2\x9c\x93' in piped.buffer.getvalue()


def test_ensure_utf8_output_leaves_utf8_streams_and_capture_alone(
    mocker: MockerFixture,
) -> None:
    """UTF-8 streams and test capture are left untouched.

    ``io.StringIO`` (what the test runner swaps in) reports its
    ``encoding`` as ``None``, so the falsy-encoding check skips it
    before reconfigure is ever consulted. A UTF-8 wrapper keeps its
    ``strict`` errors, proving the guard never touched it.
    """
    already_utf8 = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
    plain = io.StringIO()
    mocker.patch('sys.stdout', new=already_utf8)
    mocker.patch('sys.stderr', new=plain)

    ensure_utf8_output()

    assert already_utf8.encoding == 'utf-8'
    assert already_utf8.errors == 'strict'
    assert plain.encoding is None
    plain.write('✓')
    assert plain.getvalue() == '✓'


def test_ensure_utf8_output_skips_streams_it_cannot_or_fails_to_reconfigure(
    mocker: MockerFixture,
) -> None:
    """Encoding present, reconfigure absent or raising: no crash at entry.

    A CLI entry point must never die on stream housekeeping, whatever
    wrapper replaced the standard streams; nothing is asserted because
    the contract is that the call returns.
    """
    mocker.patch('sys.stdout', new=_NoReconfigure())
    mocker.patch('sys.stderr', new=_BrokenReconfigure())

    ensure_utf8_output()
