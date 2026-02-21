# Backwards-compatible shim: re-export types from `loader.models`.
# This keeps existing imports working while consolidating definitions in
# `loader/models.py` to avoid cyclic-import issues.

from repolish.loader.models import (
    Accumulators,
    Action,
    Decision,
    FileMode,
    Providers,
    TemplateMapping,
)

__all__ = [
    'Accumulators',
    'Action',
    'Decision',
    'FileMode',
    'Providers',
    'TemplateMapping',
]
