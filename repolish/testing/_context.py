"""Factory for synthetic ``RepolishContext`` objects used in tests."""

from __future__ import annotations

from typing import Literal

from repolish.providers.models.context import (
    GithubRepo,
    ProviderInfo,
    ProviderSession,
    RepolishContext,
    WorkspaceContext,
)

_Mode = Literal['root', 'member', 'standalone']


def make_context(
    *,
    mode: _Mode = 'standalone',
    alias: str = 'test-provider',
    version: str = '0.1.0',
    repo_owner: str = 'test-owner',
    repo_name: str = 'test-repo',
) -> RepolishContext:
    """Build a :class:`RepolishContext` with sensible defaults.

    Provider tests need a ``repolish`` namespace on their context but
    constructing the full object graph is tedious.  This factory fills
    every field with plausible defaults so tests only override the values
    they care about.

    Returns:
        A fully-populated :class:`RepolishContext` ready to be assigned to
        ``context.repolish``.
    """
    return RepolishContext(
        repo=GithubRepo(owner=repo_owner, name=repo_name),
        workspace=WorkspaceContext(mode=mode),
        provider=ProviderInfo(
            alias=alias,
            version=version,
            session=ProviderSession(mode=mode),
        ),
    )
