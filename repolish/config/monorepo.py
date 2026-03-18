"""Monorepo detection and member discovery.

Three public helpers:

- :func:`detect_monorepo` — sniff ``[tool.uv.workspace]`` in ``pyproject.toml``.
- :func:`detect_monorepo_from_config` — same but uses an explicit member list
  from a ``MonorepoConfig`` object.
- :func:`check_running_from_member` — walk parent dirs to find whether the
  current directory is inside a uv workspace member.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from repolish.config.models.project import MonorepoConfig
from repolish.loader.models.context import MemberInfo, MonorepoContext


def _read_uv_workspace_members(pyproject: Path) -> list[str] | None:
    """Return the raw member glob patterns from ``[tool.uv.workspace]``, or None."""
    try:
        with pyproject.open('rb') as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return data.get('tool', {}).get('uv', {}).get('workspace', {}).get('members')


def _read_project_name(pyproject: Path) -> str:
    """Return ``[project].name`` from a ``pyproject.toml``, or empty string on failure."""
    try:
        with pyproject.open('rb') as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return ''
    return data.get('project', {}).get('name', '')


def _build_member_info(member_dir: Path, config_dir: Path) -> MemberInfo | None:
    """Build a :class:`MemberInfo` for *member_dir* if it has a ``repolish.yaml``.

    Returns ``None`` when the directory has no ``repolish.yaml`` (silently skipped).
    """
    repolish_yaml = member_dir / 'repolish.yaml'
    if not repolish_yaml.exists():
        return None

    name = _read_project_name(member_dir / 'pyproject.toml')

    # Parse provider aliases from the member's repolish.yaml.
    # Imported locally to avoid a heavy import chain at module level.
    from repolish.config.loader import load_config_file  # noqa: PLC0415

    try:
        raw = load_config_file(repolish_yaml)
        provider_aliases: frozenset[str] = frozenset(raw.providers.keys())
    except Exception:  # noqa: BLE001 - broken member config should not abort root detection
        provider_aliases = frozenset()

    return MemberInfo(
        path=member_dir.relative_to(config_dir),
        name=name,
        provider_aliases=provider_aliases,
    )


def _expand_members(patterns: list[str], config_dir: Path) -> list[MemberInfo]:
    """Glob-expand workspace member patterns and collect linkable members."""
    members: list[MemberInfo] = []
    for pattern in patterns:
        for candidate in sorted(config_dir.glob(pattern)):
            if not candidate.is_dir():
                continue
            info = _build_member_info(candidate, config_dir)
            if info is not None:
                members.append(info)
    return members


def detect_monorepo(config_dir: Path) -> MonorepoContext | None:
    """Detect monorepo topology by reading ``[tool.uv.workspace]`` in ``pyproject.toml``.

    Returns a :class:`MonorepoContext` with ``mode="root"`` when a workspace is
    found, or ``None`` when the directory is a standalone repo.
    """
    pyproject = config_dir / 'pyproject.toml'
    patterns = _read_uv_workspace_members(pyproject)
    if not patterns:
        return None

    members = _expand_members(patterns, config_dir)
    return MonorepoContext(mode='root', root_dir=config_dir, members=members)


def detect_monorepo_from_config(
    config_dir: Path,
    monorepo_config: MonorepoConfig,
) -> MonorepoContext | None:
    """Detect monorepo using an explicit member list from ``repolish.yaml``.

    When ``monorepo_config.members`` is ``None`` or empty, falls back to
    :func:`detect_monorepo`.
    """
    if not monorepo_config.members:
        return detect_monorepo(config_dir)

    members = _expand_members(monorepo_config.members, config_dir)
    return MonorepoContext(mode='root', root_dir=config_dir, members=members)


def check_running_from_member(config_dir: Path) -> Path | None:
    """Return the monorepo root if *config_dir* is a member, else ``None``.

    Walks parent directories until it finds a ``pyproject.toml`` with a
    ``[tool.uv.workspace]`` whose expanded member globs contain *config_dir*.
    Stops at the filesystem root.
    """
    config_dir = config_dir.resolve()
    current = config_dir.parent

    while True:
        pyproject = current / 'pyproject.toml'
        if pyproject.exists():
            patterns = _read_uv_workspace_members(pyproject)
            if patterns:
                for pattern in patterns:
                    for candidate in current.glob(pattern):
                        if candidate.resolve() == config_dir:
                            return current
        parent = current.parent
        if parent == current:
            # reached filesystem root
            break
        current = parent

    return None
