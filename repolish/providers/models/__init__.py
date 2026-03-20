"""Loader models package: re-exports the full public API from all submodules.

Consumers should import from `repolish.providers.models` (this package) rather
than from the individual submodules. The split into submodules is an
implementation detail:

- `workspace` — `MemberInfo`, `WorkspaceContext`, `WorkspaceProviderInfo`
- `context` — `Symlink`, `GithubRepo`, `GlobalContext`, `get_global_context`,
  `ProviderInfo`, `BaseContext`, `BaseInputs`
- `pipeline` — `PipelineOptions`, `DryRunResult`
- `files` — `Action`, `Decision`, `FileMode`, `TemplateMapping`, `FileRecord`,
  `SessionBundle`, `Accumulators`, `build_file_records`
- `provider` — `ProviderEntry`, `Provider`, `get_provider_inputs_schema`,
  `get_provider_inputs`, `get_provider_context`
"""

from repolish.providers.models.context import (
    BaseContext,
    BaseInputs,
    GithubRepo,
    GlobalContext,
    ProviderInfo,
    Symlink,
    get_global_context,
)
from repolish.providers.models.files import (
    Accumulators,
    Action,
    Decision,
    FileMode,
    FileRecord,
    SessionBundle,
    TemplateMapping,
    build_file_records,
)
from repolish.providers.models.pipeline import DryRunResult, PipelineOptions
from repolish.providers.models.provider import (
    ContextT,
    InputT,
    Provider,
    ProviderEntry,
    T,
    get_provider_context,
    get_provider_inputs,
    get_provider_inputs_schema,
)
from repolish.providers.models.workspace import (
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
    'SessionBundle',
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
