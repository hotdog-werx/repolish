"""Context models: global template namespace, provider runtime metadata, and base classes.

Defines the building blocks that flow into every provider's context object:

- `Symlink` — return type of `Provider.create_default_symlinks`
- `GithubRepo` / `GlobalContext` / `get_global_context` — repo-level globals
- `ProviderInfo` — alias/version injected by the loader at runtime
- `BaseContext` / `BaseInputs` — base classes for provider contexts and inputs

Workspace topology models (`MemberInfo`, `WorkspaceContext`,
`WorkspaceProviderInfo`) live in `loader.models.workspace` and are
re-exported here for convenience.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    computed_field,
)

from repolish.loader.models.workspace import (
    MemberInfo,
    WorkspaceContext,
    WorkspaceProviderInfo,
)

__all__ = [
    'MemberInfo',
    'WorkspaceContext',
    'WorkspaceProviderInfo',
]


@dataclass
class Symlink:
    """A symlink from provider resources to the project.

    Used as the return type of :meth:`Provider.create_default_symlinks`.
    Paths are plain strings; the linker resolves them relative to the
    provider's ``resources_dir`` (source) and the project root (target).
    """

    source: str
    target: str


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


def _get_owner_repo() -> tuple[str, str]:
    """Parse the git remote 'origin' URL and return (owner, repo_name).

    Supports HTTPS and SSH GitHub URL formats.  Raises `ValueError` if the
    URL cannot be parsed.
    """
    import re  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    remote = subprocess.check_output(
        ['git', 'remote', 'get-url', 'origin'],  # noqa: S607
        text=True,
    ).strip()
    match = re.search(
        r'(?:https://(?:[^/]+@)?github\.com/|git@github\.com:)([^/]+)/([^.]+)(?:\.git)?$',
        remote,
    )
    if match:
        return match.group(1), match.group(2)
    msg = f'No owner/repo found in git remote URL: {remote}'
    raise ValueError(msg)


def get_global_context() -> GlobalContext:
    """Return a model populated from the current repository settings.

    The implementation is intentionally forgiving; any failure to extract
    information (for example when not running inside a git repository) is
    swallowed and the returned object will simply have default values.  The
    loader calls this during startup and injects the result directly into
    every provider context so the ``repolish`` namespace is available to all
    providers and templates.
    """
    try:
        owner, name = _get_owner_repo()
    except Exception:  # noqa: BLE001
        owner = name = 'Unknown'
    return GlobalContext(
        repo=GithubRepo(owner=owner, name=name),
        year=datetime.datetime.now(datetime.UTC).year,
    )


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

    SessionBundle almost always define their own context model, but when no
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
    for type checking and tooling.  SessionBundle that declare an input schema
    but don't need any fields can use this empty class as a default.
    """
