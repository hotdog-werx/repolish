"""Loader models package: re-exports the full public API from all submodules.

Consumers should import from `repolish.providers.models` (this package) rather
than from the individual submodules. The split into submodules is an
implementation detail:

- `workspace` — `MemberInfo`, `WorkspaceContext`, `ProviderSession`
- `context` — `Symlink`, `GithubRepo`, `GlobalContext`, `get_global_context`,
  `ProviderInfo`, `RepolishContext`, `BaseContext`, `BaseInputs`
- `pipeline` — `PipelineOptions`, `DryRunResult`
- `files` — `Action`, `Decision`, `FileMode`, `TemplateMapping`, `FileRecord`,
  `SessionBundle`, `Accumulators`, `build_file_records`
- `provider` — `ProviderEntry`, `Provider`, `ModeHandler`, `ProvideInputsOptions`,
  `FinalizeContextOptions`, `get_provider_inputs_schema`,
  `get_provider_inputs`, `get_provider_context`
"""

from repolish.providers.models.context import (
    BaseContext,
    BaseInputs,
    GithubRepo,
    GlobalContext,
    ProviderInfo,
    RepolishContext,
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
    map_folder,
)
from repolish.providers.models.pipeline import DryRunResult, PipelineOptions
from repolish.providers.models.provider import (
    ContextT,
    FinalizeContextOptions,
    InputT,
    ModeHandler,
    ProvideInputsOptions,
    Provider,
    ProviderEntry,
    T,
    call_provider_method,
    get_provider_context,
    get_provider_inputs,
    get_provider_inputs_schema,
)
from repolish.providers.models.workspace import (
    MemberInfo,
    ProviderSession,
    WorkspaceContext,
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
    'FinalizeContextOptions',
    'GithubRepo',
    'GlobalContext',
    'InputT',
    'MemberInfo',
    'ModeHandler',
    'PipelineOptions',
    'ProvideInputsOptions',
    'Provider',
    'ProviderEntry',
    'ProviderInfo',
    'ProviderSession',
    'RepolishContext',
    'SessionBundle',
    'Symlink',
    'T',
    'TemplateMapping',
    'WorkspaceContext',
    'build_file_records',
    'call_provider_method',
    'get_global_context',
    'get_provider_context',
    'get_provider_inputs',
    'get_provider_inputs_schema',
    'map_folder',
]
