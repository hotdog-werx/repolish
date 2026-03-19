"""Context models: global template namespace, provider runtime metadata, and base classes.

Defines the building blocks that flow into every provider's context object:
- :class:`Symlink` — return type of :meth:`~repolish.loader.models.Provider.create_default_symlinks`
- :class:`GithubRepo` / :class:`GlobalContext` / :func:`get_global_context` — repo-level globals
- :class:`ProviderInfo` — alias/version injected by the loader at runtime
- :class:`BaseContext` / :class:`BaseInputs` — base classes for provider contexts and inputs
- :class:`MemberInfo` / :class:`MonorepoContext` — monorepo topology exposed to providers
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    computed_field,
    field_serializer,
)


@dataclass
class Symlink:
    """A symlink from provider resources to the project.

    Used as the return type of :meth:`Provider.create_default_symlinks`.
    Paths are plain strings; the linker resolves them relative to the
    provider's ``resources_dir`` (source) and the project root (target).
    """

    source: str
    target: str


class MemberInfo(BaseModel):
    """Metadata about a single monorepo member directory.

    Available in templates via ``{{ repolish.monorepo.members }}``.
    """

    model_config = ConfigDict(frozen=True)

    path: Path
    """Repo-relative path to the member directory (e.g. ``packages/core``)."""
    name: str
    """Package name from the member's ``pyproject.toml`` ``[project].name``."""
    provider_aliases: frozenset[str]
    """Provider keys declared in the member's ``repolish.yaml``."""

    @field_serializer('path')
    def _serialize_path(self, v: Path) -> str:
        return v.as_posix()

    @field_serializer('provider_aliases')
    def _serialize_provider_aliases(self, v: frozenset[str]) -> list[str]:
        return sorted(v)


class WorkspaceContext(BaseModel):
    """Monorepo topology injected into every provider context as ``repolish.monorepo``.

    In standalone mode all fields retain their defaults so existing providers
    are unaffected.  When repolish detects a monorepo (or is told about one
    via ``repolish.yaml``), this object communicates the current execution
    role and the full list of members.
    """

    model_config = ConfigDict(frozen=True)

    mode: Literal['root', 'package', 'standalone'] = 'standalone'
    root_dir: Path = Field(default_factory=Path.cwd)
    package_dir: Path | None = None
    members: list[MemberInfo] = Field(default_factory=list)

    @field_serializer('root_dir')
    def _serialize_root_dir(self, v: Path) -> str:
        return v.as_posix()

    @field_serializer('package_dir')
    def _serialize_package_dir(self, v: Path | None) -> str | None:
        return v.as_posix() if v is not None else None


class GithubRepo(BaseModel):
    """Model representing a GitHub repository identifier.

    Historically the global context exposed ``repo_owner`` and
    ``repo_name`` as two separate fields.  They have been consolidated into a
    single nested object here to make the structure easier to work with in
    templates and to allow additional repository metadata in the future.
    """

    owner: str = 'UnknownOwner'
    name: str = 'UnknownRepo'


class GlobalContext(BaseModel):
    """Globally-available values injected into every provider context.

    By default the loader only populates the GitHub repository information
    (read from the ``origin`` remote).  Additional keys may be added in
    future releases.  The value is exposed to templates as ``repolish`` (see
    :mod:`docs.configuration.context` for details) and the typed field is
    available to class-based providers that inherit from :class:`BaseContext`.

    ``GlobalContext`` is intentionally trivial so consumer code can import
    it directly when typing provider contexts; providers that don't declare
    a subclass of :class:`~repolish.loader.models.BaseContext` simply ignore
    it.
    """

    repo: GithubRepo = Field(default_factory=GithubRepo)
    # `year` is intentionally coarse-grained; it's useful for license
    # headers and other boilerplate that should not require manual updates
    # when the calendar rolls over.  The value is computed when the model is
    # instantiated so repeated loader runs within the same year remain
    # consistent yet automatically advance at New Year's.
    year: int = Field(
        default_factory=lambda: datetime.datetime.now(
            datetime.UTC,
        ).year,
    )
    workspace: WorkspaceContext = Field(default_factory=WorkspaceContext)


def get_global_context() -> GlobalContext:
    """Return a model populated from the current repository settings.

    The implementation is intentionally forgiving; any failure to extract
    information (for example when not running inside a git repository) is
    swallowed and the returned object will simply have default values.  The
    loader calls this during startup and injects the result directly into
    every provider context so the ``repolish`` namespace is available to all
    providers and templates.
    """
    # imported locally to avoid a circular dependency when the loader tests
    # import the helper without needing the providers package.
    from repolish.providers import git  # noqa: PLC0415 - local import avoids circular

    try:
        owner, name = git.get_owner_repo()
    except Exception:  # noqa: BLE001
        owner = name = 'Unknown'
    # explicitly compute the year here as well; this mirrors the default
    # factory and ensures callers that bypass the default still receive a
    # sensible value.
    return GlobalContext(
        repo=GithubRepo(owner=owner, name=name),
        year=datetime.datetime.now(datetime.UTC).year,
    )


class WorkspaceProviderInfo(BaseModel):
    """Monorepo identity of the provider instance, injected into ``_provider``.

    Unlike ``repolish.monorepo`` (which is global and shared), these fields
    describe *this* provider's own role in the monorepo — its mode and, when
    running as a package member, its name and repo-relative path.

    Available in templates as ``{{ _provider.monorepo.mode }}``,
    ``{{ _provider.monorepo.member_name }}``, etc.
    """

    mode: Literal['root', 'package', 'standalone'] = 'standalone'
    member_name: str = ''
    """Package name of this member (from its ``pyproject.toml``), e.g. ``pkg-alpha``."""
    member_path: str = ''
    """Repo-relative POSIX path to this member directory, e.g. ``packages/pkg-alpha``."""


class ProviderInfo(BaseModel):
    """Runtime metadata injected into every provider context by the loader.

    Available in templates as ``{{ _provider.alias }}``, ``{{ _provider.version }}``
    and ``{{ _provider.major_version }}``.  All fields default to empty/None so
    providers that don't need the information aren't forced to handle it.
    """

    alias: str = ''
    version: str = ''
    package_name: str = ''
    project_name: str = ''
    monorepo: WorkspaceProviderInfo = Field(
        default_factory=WorkspaceProviderInfo,
    )
    """Monorepo identity: mode and, for package members, name and path."""

    @computed_field
    @property
    def major_version(self) -> int | None:
        """Integer major version parsed from ``version``, or None if unavailable."""
        if not self.version:
            return None
        try:
            return int(self.version.split('.')[0].lstrip('v'))
        except (ValueError, IndexError):
            return None


class BaseContext(BaseModel):
    """Minimal, empty context type for providers.

    Providers almost always define their own context model, but when no
    fields are needed this class can be used as a lightweight default.  It
    avoids the awkward requirement that `BaseModel` itself cannot be
    instantiated and keeps callers from having to import Pydantic directly -
    you can `from repolish import BaseContext`.

    Historically many tests and examples simply used `BaseModel` for this
    purpose, which triggered errors and confusion.  `BaseContext` is the
    safer, idiomatic alternative.
    """

    repolish: GlobalContext = Field(default_factory=GlobalContext)
    _provider_data: ProviderInfo = PrivateAttr(default_factory=ProviderInfo)

    @computed_field
    @property
    def _provider(self) -> ProviderInfo:
        """Provider metadata injected by the loader (alias, version, major_version)."""
        return self._provider_data


class BaseInputs(BaseModel):
    """Base class for provider inputs.

    This is not strictly necessary since providers can declare any Pydantic
    model as their input schema, but it provides a convenient shared parent
    for type checking and tooling.  Providers that declare an input schema
    but don't need any fields can use this empty class as a default.
    """
