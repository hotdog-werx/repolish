"""Provider registration: module-first linking with the CLI path quarantined.

This package is the registration engine that guarantees every configured
provider's resources live under ``.repolish/`` before apply or link runs.
The durable link-creation core moved to :mod:`repolish.links` and the
subprocess bridge to ``cli:``-declared providers to
:mod:`repolish.cli_registry`; both stay re-exported here so the public
import surface (``from repolish.linker import link_resources``,
``resource_linker_cli``, ``run_provider_link``, ...) is unchanged.
"""

from repolish.cli_registry import (
    probe_provider_info,
    run_provider_link,
)
from repolish.linker.health import (
    ProviderReadinessResult,
    ensure_providers_ready,
)
from repolish.linker.module_link import (
    probe_module_info,
    run_module_link,
)
from repolish.linker.orchestrator import (
    collect_provider_copies,
    collect_provider_symlinks,
    create_provider_copies,
    create_provider_symlinks,
    process_provider,
)
from repolish.linker.providers import (
    save_provider_alias,
    save_provider_info,
    write_provider_info_file,
)
from repolish.links import (
    create_additional_link,
    link_resources,
    resource_linker,
    resource_linker_cli,
)
from repolish.providers.models import ResourceCopy, Symlink

__all__ = [
    'ProviderReadinessResult',
    'ResourceCopy',
    'Symlink',
    'collect_provider_copies',
    'collect_provider_symlinks',
    'create_additional_link',
    'create_provider_copies',
    'create_provider_symlinks',
    'ensure_providers_ready',
    'link_resources',
    'probe_module_info',
    'probe_provider_info',
    'process_provider',
    'resource_linker',
    'resource_linker_cli',
    'run_module_link',
    'run_provider_link',
    'save_provider_alias',
    'save_provider_info',
    'write_provider_info_file',
]
