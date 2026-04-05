"""Shared Rich console for repolish CLI output."""

import os
import sys

from rich.console import Console

# Disable colors during tests (similar to hotlog's get_console behavior)
_in_pytest = 'pytest' in sys.modules or any(k.startswith('PYTEST_') for k in os.environ)
_force_terminal = not _in_pytest
console = Console(force_terminal=_force_terminal)

# OSC 8 hyperlinks are invisible in CI log viewers (GitHub Actions, etc.)
# that don't support the sequence.  Only enable them in a real interactive
# terminal outside of CI.
_ci_raw = os.environ.get('CI', '').strip().lower()
_in_ci = _ci_raw in ('1', 'true', 'yes')
supports_hyperlinks = not _in_pytest and not _in_ci
