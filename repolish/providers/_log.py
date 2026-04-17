"""Singleton logger for the `repolish.providers` package.

Provide a single `logger` instance imported by submodules so tests can
monkeypatch `repolish.providers.logger` (the package barrel exports it).
"""

from hotlog import get_logger

logger = get_logger('repolish.providers')
