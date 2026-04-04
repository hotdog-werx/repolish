from pathlib import Path

from hotlog import get_logger

from repolish.commands.apply.symlinks import apply_symlinks
from repolish.commands.apply.utils import chdir
from repolish.config import RepolishConfigFile, load_config_file
from repolish.config.resolution import resolve_config
from repolish.config.topology import (
    detect_workspace,
    detect_workspace_from_config,
)
from repolish.linker.health import ensure_providers_ready
from repolish.linker.orchestrator import collect_provider_symlinks
from repolish.providers.models.context import WorkspaceContext

logger = get_logger(__name__)


def _get_provider_names(config: RepolishConfigFile) -> list[str]:
    """Get list of provider names in the correct order.

    Args:
        config: Raw repolish configuration file

    Returns:
        List of provider names to process (from providers_order or providers dict key order)
    """
    if config.providers_order:
        return config.providers_order
    # If no order specified, use providers dict key order (preserves YAML order)
    return list(config.providers.keys())


def _link_config(config_path: Path) -> int:
    """Run ensure_providers_ready for the config at *config_path*. Returns 0 or 1."""
    config = load_config_file(config_path)
    if not config.providers:
        return 0
    provider_names = _get_provider_names(config)
    logger.info('linking_providers', providers=provider_names, _display_level=1)
    result = ensure_providers_ready(
        provider_names,
        config.providers,
        config_path.resolve().parent,
        force=True,
    )
    if result.failed:
        logger.warning(
            'some_providers_not_linked',
            failed=result.failed,
            _display_level=1,
        )
        return 1
    resolved = resolve_config(config)
    resolved_symlinks = collect_provider_symlinks(
        resolved.providers,
        config.providers,
    )
    apply_symlinks(resolved_symlinks, resolved.providers)
    return 0


def _detect_workspace(
    config: RepolishConfigFile,
    config_dir: Path,
) -> WorkspaceContext | None:
    if config.workspace and config.workspace.members:
        return detect_workspace_from_config(config_dir, config.workspace)
    return detect_workspace(config_dir)


def _link_members(mono_ctx: WorkspaceContext, config_dir: Path) -> int:
    """Link providers in every member directory. Returns 0 on full success, 1 on any failure."""
    for m in mono_ctx.members:
        member_dir = (config_dir / m.path).resolve()
        member_config = member_dir / 'repolish.yaml'
        if not member_config.exists():
            continue
        logger.info('linking_member', member=m.name, _display_level=1)
        with chdir(member_dir):
            rc = _link_config(member_config)
        if rc != 0:
            return rc
    return 0


def command(config_path: Path) -> int:
    """Run repolish link with the given config."""
    logger.info(
        'loading_config',
        config_file=str(config_path),
        _display_level=1,
    )
    config = load_config_file(config_path)
    config_dir = config_path.resolve().parent

    mono_ctx = _detect_workspace(config, config_dir)

    if mono_ctx is not None:
        # Root pass first, then every member.
        rc = _link_config(config_path)
        if rc != 0:
            return rc
        return _link_members(mono_ctx, config_dir)

    if not config.providers:
        logger.warning('no_providers_configured', _display_level=1)
        return 0

    return _link_config(config_path)
