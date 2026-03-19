"""Configuration model package.

All concrete model definitions live in submodules (project.py, provider.py,
metadata.py) to improve organization.  This package init simply re-exports
public names for convenience.

Codebase references `repolish.config.models` throughout; with this package
in place the old import style continues to work and new code can import more
selectively if desired.
"""

from .metadata import AllProviders, ProviderFileInfo
from .project import RepolishConfig, RepolishConfigFile, WorkspaceConfig
from .provider import ProviderConfig, ProviderSymlink, ResolvedProviderInfo

__all__ = [
    'AllProviders',
    'ProviderConfig',
    'ProviderFileInfo',
    'ProviderSymlink',
    'RepolishConfig',
    'RepolishConfigFile',
    'ResolvedProviderInfo',
    'WorkspaceConfig',
]
