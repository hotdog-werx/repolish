"""Shared console and output helpers for the repolish CLI."""

from __future__ import annotations

import codecs
import os
import sys
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from pathlib import Path

# Disable colors during tests (similar to hotlog's get_console behavior)
_in_pytest = 'pytest' in sys.modules or any(k.startswith('PYTEST_') for k in os.environ)
_force_terminal = not _in_pytest


def build_console(**kwargs: Any) -> Console:
    """Build the console every repolish render goes through.

    ``legacy_windows=False`` keeps Rich off its Win32 legacy renderer.
    Rich enables it from a virtual-terminal probe, but a std stream that
    is a pipe (a task runner piping output, a Git Bash terminal) fails
    the probe and still passes Rich's std-stream check, so Rich hands
    the pipe to ``LegacyWindowsTerm``, whose console-API calls cannot
    work on it: the run dies on the first render. Real Windows consoles
    have processed ANSI escape sequences since Windows 10, so the legacy
    renderer has nothing left to serve.
    """
    return Console(legacy_windows=False, **kwargs)


console = build_console(force_terminal=_force_terminal)

# OSC 8 hyperlinks are invisible in CI log viewers (GitHub Actions, etc.)
# that don't support the sequence.  Only enable them in a real interactive
# terminal outside of CI.
_ci_raw = os.environ.get('CI', '').strip().lower()
_in_ci = _ci_raw in ('1', 'true', 'yes')
supports_hyperlinks = not _in_pytest and not _in_ci


def hyperlink_style(path: Path | None, prefix: str = '') -> str:
    """Return the Rich style that turns a label into a `file://` hyperlink.

    The URI comes from ``Path.as_uri()``. Splicing the path into
    ``file://{path}`` only works on POSIX, where absolute paths start
    with a slash; on Windows the drive letter lands in the URL's host
    position (`file://C:/Users/...`), and the terminal resolves the link
    to a path that does not exist. ``as_uri()`` keeps the drive in the
    path (`file:///C:/Users/...`) and percent-encodes spaces. Returns
    *prefix* alone when *path* is ``None`` or the console does not
    support hyperlinks, so unlinked labels keep their plain styling.
    """
    if path is None or not supports_hyperlinks:
        return prefix
    style = f'link {path.absolute().as_uri()}'
    return f'{prefix} {style}' if prefix else style


def ensure_utf8_output() -> None:
    """Reconfigure non-UTF-8 standard streams to UTF-8 in place.

    A piped stdout on Windows encodes with the ANSI code page (cp1252
    and friends), which cannot hold the summary tree's glyphs, so the
    first render dies with rich's ``PYTHONIOENCODING`` advice after the
    work is already done. Python 3.15 makes UTF-8 the default (PEP 686);
    until every runtime has that, each CLI entry point calls this so no
    user needs the env var. Streams already speaking UTF-8 or declaring
    no encoding (test capture, plain ``io.StringIO``), and streams
    without a reconfigure to call, are left alone; a reconfigure that
    raises never kills the entry. ``errors="replace"`` only ever turns
    lone surrogates from undecodable filesystem paths into ``?``: UTF-8
    encodes every glyph.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, 'encoding', None)
        if not encoding or codecs.lookup(encoding).name == 'utf-8':
            continue
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding='utf-8', errors='replace')
        except (ValueError, OSError):
            continue
