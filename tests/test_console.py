"""Tests for the console factory every repolish render goes through."""

from pathlib import Path

from pytest_mock import MockerFixture

from repolish.console import build_console, hyperlink_style


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
