"""Utilities exposed to test modules.

Rather than sprinkling imports from ``tests.support.fs`` throughout the
suite we re-export the most commonly used helpers here.  This also keeps the
public API simple for new tests.
"""

from tests.support.fs import module_name_from_path, write_module

__all__ = [
    'module_name_from_path',
    'write_module',
]
