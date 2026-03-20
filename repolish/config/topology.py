from pathlib import Path

from repolish.config.models.project import WorkspaceConfig
from repolish.providers.models.context import MemberInfo, WorkspaceContext
from repolish.misc import read_toml


def _read_uv_workspace_members(pyproject: Path) -> list[str] | None:
    """Return the raw member glob patterns from ``[tool.uv.workspace]``, or None."""
    data = read_toml(pyproject)
    if data:
        members = data.get('tool', {}).get('uv', {}).get('workspace', {}).get('members')
        if isinstance(members, list) and all(isinstance(m, str) for m in members):
            return members
    return None


def _read_project_name(pyproject: Path) -> str:
    """Return ``[project].name`` from a ``pyproject.toml``, or empty string on failure."""
    data = read_toml(pyproject)
    return data.get('project', {}).get('name', '') or '' if data else ''


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


def detect_workspace(config_dir: Path) -> WorkspaceContext | None:
    """Detect workspace topology by reading ``[tool.uv.workspace]`` in ``pyproject.toml``.

    Returns a :class:`WorkspaceContext` with ``mode="root"`` when a workspace is
    found, or ``None`` when the directory is a standalone repo.
    """
    pyproject = config_dir / 'pyproject.toml'
    patterns = _read_uv_workspace_members(pyproject)
    if not patterns:
        return None

    members = _expand_members(patterns, config_dir)
    return WorkspaceContext(mode='root', root_dir=config_dir, members=members)


def detect_workspace_from_config(
    config_dir: Path,
    workspace_config: WorkspaceConfig,
) -> WorkspaceContext | None:
    """Detect workspace using an explicit member list from ``repolish.yaml``.

    When ``workspace_config.members`` is ``None`` or empty, falls back to
    :func:`detect_workspace`.
    """
    if not workspace_config.members:
        return detect_workspace(config_dir)

    members = _expand_members(workspace_config.members, config_dir)
    return WorkspaceContext(mode='root', root_dir=config_dir, members=members)


def find_workspace_root(config_dir: Path) -> Path | None:
    """Return the workspace root path if *config_dir* is a workspace member.

    Walks parent directories until it finds a ``pyproject.toml`` with a
    ``[tool.uv.workspace]`` section whose expanded member globs contain
    *config_dir*.  Returns the directory containing that ``pyproject.toml``,
    or ``None`` if no matching workspace root is found before the filesystem
    root.
    """
    config_dir = config_dir.resolve()

    # Iterate through the parent chain (including the filesystem root)
    for current in (config_dir.parent, *config_dir.parent.parents):
        pyproject = current / 'pyproject.toml'
        if not pyproject.exists():
            continue

        patterns = _read_uv_workspace_members(pyproject)
        if not patterns:
            continue

        if any(candidate.resolve() == config_dir for pattern in patterns for candidate in current.glob(pattern)):
            return current

    return None
