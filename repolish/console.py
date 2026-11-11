"""Shared Rich console for repolish CLI output."""

from __future__ import annotations

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
