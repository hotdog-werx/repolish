"""Workspace and monorepo topology models.

These models describe the structure of the repository from repolish's point
of view. They are injected into every provider context so templates can
react to whether they are running in a standalone project, a monorepo root,
or a monorepo member.

- `MemberInfo` — metadata about one monorepo member directory
- `WorkspaceContext` — full topology: mode, root, package dir, all members
- `WorkspaceProviderInfo` — this provider's own role within the monorepo
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class MemberInfo(BaseModel):
    """Metadata about a single monorepo member directory.

    Exposed in templates as individual items inside `repolish.workspace.members`.
    """

    model_config = ConfigDict(frozen=True)

    path: Path
    """Repo-relative path to the member directory (e.g. `packages/core`)."""
    name: str
    """Package name from the member's `pyproject.toml` `[project].name`."""
    provider_aliases: frozenset[str]
    """Provider keys declared in the member's `repolish.yaml`."""

    @field_serializer('path')
    def _serialize_path(self, v: Path) -> str:
        return v.as_posix()

    @field_serializer('provider_aliases')
    def _serialize_provider_aliases(self, v: frozenset[str]) -> list[str]:
        return sorted(v)


class WorkspaceContext(BaseModel):
    """Monorepo topology injected into every provider context as `repolish.workspace`.

    In standalone mode all fields retain their defaults so existing providers
    are unaffected. When repolish detects a monorepo (or is told about one
    via `repolish.yaml`), this object communicates the current execution
    role and the full list of members.
    """

    model_config = ConfigDict(frozen=True)

    mode: Literal['root', 'member', 'standalone'] = 'standalone'
    root_dir: Path = Field(default_factory=Path.cwd)
    package_dir: Path | None = None
    members: list[MemberInfo] = Field(default_factory=list)

    @field_serializer('root_dir')
    def _serialize_root_dir(self, v: Path) -> str:
        return v.as_posix()

    @field_serializer('package_dir')
    def _serialize_package_dir(self, v: Path | None) -> str | None:
        return v.as_posix() if v is not None else None


class WorkspaceProviderInfo(BaseModel):
    """This provider's own role within the monorepo, injected into `_provider.monorepo`.

    Unlike `repolish.workspace` (which is global and shared across all
    providers in the session), these fields describe the role of *this specific
    provider instance* — its mode and, when running as a monorepo member, its
    name and repo-relative path.

    Available in templates as `{{ _provider.monorepo.mode }}`,
    `{{ _provider.monorepo.member_name }}`, etc.
    """

    mode: Literal['root', 'member', 'standalone'] = 'standalone'
    member_name: str = ''
    """Package name of this member (from its `pyproject.toml`), e.g. `pkg-alpha`."""
    member_path: str = ''
    """Repo-relative POSIX path to this member directory, e.g. `packages/pkg-alpha`."""
