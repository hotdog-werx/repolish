"""Loader package public barrel.

This module re-exports the public loader API. Keep this file small and
free of implementation logic so imports remain cheap and easy to
reference from the rest of the codebase.
"""

from repolish.loader._log import logger
from repolish.loader.deletes import (
    normalize_delete_item,
    normalize_delete_items,
)
from repolish.loader.models import (
    Accumulators,
    Action,
    BaseContext,
    Decision,
    FileMode,
    Provider,
    ProviderEntry,
    Providers,
    TemplateMapping,
    get_provider_context,
)
from repolish.loader.orchestrator import create_providers

__all__ = [
    'Accumulators',
    'Action',
    'BaseContext',
    'Decision',
    'FileMode',
    'Provider',
    'ProviderEntry',
    'Providers',
    'TemplateMapping',
    'create_providers',
    'get_provider_context',
    'logger',
    'normalize_delete_item',
    'normalize_delete_items',
]
