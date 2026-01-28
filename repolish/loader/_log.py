"""Singleton logger for the `repolish.loader` package.

Provide a single `logger` instance imported by submodules so tests can
monkeypatch `repolish.loader.logger` (the package barrel exports it).
"""

from hotlog import get_logger

logger = get_logger('repolish.loader')
