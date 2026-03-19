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
    SessionBundle,
    TemplateMapping,
    get_provider_context,
)
from repolish.loader.models.pipeline import DryRunResult, PipelineOptions
from repolish.loader.orchestrator import create_providers

__all__ = [
    'Action',
    'BaseContext',
    'Decision',
    'DryRunResult',
    'FileMode',
    'PipelineOptions',
    'Provider',
    'ProviderEntry',
    'ProviderInfo',
    'SessionBundle',
    'TemplateMapping',
    'create_providers',
    'get_provider_context',
    'logger',
]
