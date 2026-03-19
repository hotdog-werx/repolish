"""Loader models package: re-exports the full public API from all submodules.

Consumers should import from `repolish.loader.models` (this package) rather
than from the individual submodules. The split into submodules is an
implementation detail:

- `workspace` — `MemberInfo`, `WorkspaceContext`, `WorkspaceProviderInfo`
- `context` — `Symlink`, `GithubRepo`, `GlobalContext`, `get_global_context`,
  `ProviderInfo`, `BaseContext`, `BaseInputs`
- `pipeline` — `PipelineOptions`, `DryRunResult`
- `files` — `Action`, `Decision`, `FileMode`, `TemplateMapping`, `FileRecord`,
  `Providers`, `Accumulators`, `build_file_records`
- `provider` — `ProviderEntry`, `Provider`, `get_provider_inputs_schema`,
  `get_provider_inputs`, `get_provider_context`
"""

from repolish.loader.models.context import (
    BaseContext,
    BaseInputs,
    GithubRepo,
    GlobalContext,
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
from repolish.loader.models.pipeline import DryRunResult, PipelineOptions
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
from repolish.loader.models.workspace import (
    MemberInfo,
    WorkspaceContext,
    WorkspaceProviderInfo,
)

__all__ = [
    'Accumulators',
    'Action',
    'BaseContext',
    'BaseInputs',
    'ContextT',
    'Decision',
    'DryRunResult',
    'FileMode',
    'FileRecord',
    'GithubRepo',
    'GlobalContext',
    'InputT',
    'MemberInfo',
    'MemberInfo',
    'PipelineOptions',
    'Provider',
    'ProviderEntry',
    'ProviderInfo',
    'Providers',
    'Symlink',
    'T',
    'TemplateMapping',
    'WorkspaceContext',
    'WorkspaceProviderInfo',
    'build_file_records',
    'get_global_context',
    'get_provider_context',
    'get_provider_inputs',
    'get_provider_inputs_schema',
]
