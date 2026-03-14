"""Shared Rich console for repolish CLI output."""

import os
import sys

from rich.console import Console

# Disable colors during tests (similar to hotlog's get_console behavior)
_force_terminal = 'pytest' not in sys.modules and not any(k.startswith('PYTEST_') for k in os.environ)
console = Console(force_terminal=_force_terminal)
