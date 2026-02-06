"""Utilities for repolish providers.

This package provides helper functions and utilities that provider authors
can use in their repolish.py files to simplify common tasks like extracting
git repository information, working with files, and manipulating context data.
"""

from repolish.providers.git import get_owner_repo

__all__ = [
    'get_owner_repo',
]
