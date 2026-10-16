"""Project-local repolish provider (installable tier).

repolish loads this file directly by path, so it must stay a shim — the real
implementation lives in the installed `local_provider` package next to this
directory (see pyproject.toml), which is free to import its own sibling
modules.  Wire it up in repolish.yaml:

    providers:
      local:
        provider_root: internal/templates

Templates in the repolish/ directory next to this file are applied to the
project on every `repolish apply`.  Editable-install this directory into the
environment that runs repolish (e.g. `-e .` in its requirements), and re-run
that install whenever pyproject.toml changes.
"""

from local_provider import __version__
from local_provider.provider import LocalProvider

__all__ = ['LocalProvider', '__version__']
