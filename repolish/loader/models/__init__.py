"""Loader models package: re-exports the full public API from all submodules.

Consumers should import from ``repolish.loader.models`` (this package) rather
than from the individual submodules.  The split into submodules is an
implementation detail:

- :mod:`.context` — :class:`Symlink`, :class:`GithubRepo`, :class:`GlobalContext`,
  :func:`get_global_context`, :class:`ProviderInfo`, :class:`MonorepoProviderInfo`,
  :class:`BaseContext`, :class:`BaseInputs`, :class:`MemberInfo`, :class:`MonorepoContext`
- :mod:`.files` — :class:`Action`, :class:`Decision`, :class:`FileMode`,
  :class:`TemplateMapping`, :class:`FileRecord`, :class:`Providers`,
  :class:`Accumulators`, :func:`build_file_records`
- :mod:`.provider` — :class:`ProviderEntry`, :class:`Provider`,
  :func:`get_provider_inputs_schema`, :func:`get_provider_inputs`,
  :func:`get_provider_context`
"""

from repolish.loader.models.context import (
    BaseContext,
    BaseInputs,
    GithubRepo,
    GlobalContext,
    MemberInfo,
    MonorepoContext,
    MonorepoProviderInfo,
    ProviderInfo,
    Symlink,
    get_global_context,
)
from repolish.loader.models.files import (
    Accumulators,
    Action,
    Decision,
    FileMode,
    FileRecord,
    Providers,
    TemplateMapping,
    build_file_records,
)
from repolish.loader.models.provider import (
    ContextT,
    InputT,
    Provider,
    ProviderEntry,
    T,
    get_provider_context,
    get_provider_inputs,
    get_provider_inputs_schema,
)

__all__ = [
    'Accumulators',
    'Action',
    'BaseContext',
    'BaseInputs',
    'ContextT',
    'Decision',
    'FileMode',
    'FileRecord',
    'GithubRepo',
    'GlobalContext',
    'InputT',
    'MemberInfo',
    'MonorepoContext',
    'MonorepoProviderInfo',
    'Provider',
    'ProviderEntry',
    'ProviderInfo',
    'Providers',
    'Symlink',
    'T',
    'TemplateMapping',
    'build_file_records',
    'get_global_context',
    'get_provider_context',
    'get_provider_inputs',
    'get_provider_inputs_schema',
]
