"""Loader package public barrel.

This module re-exports the public loader API. Keep this file small and
free of implementation logic so imports remain cheap and easy to
reference from the rest of the codebase.
"""

from repolish.loader._log import logger
from repolish.loader.models import (
    Action,
    BaseContext,
    Decision,
    FileMode,
    Provider,
    ProviderEntry,
    ProviderInfo,
    Providers,
    TemplateMapping,
    get_provider_context,
)
from repolish.loader.orchestrator import create_providers
from repolish.loader.pipeline import DryRunResult

__all__ = [
    'Action',
    'BaseContext',
    'Decision',
    'DryRunResult',
    'FileMode',
    'Provider',
    'ProviderEntry',
    'ProviderInfo',
    'Providers',
    'TemplateMapping',
    'create_providers',
    'get_provider_context',
    'logger',
]
