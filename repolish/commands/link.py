from pathlib import Path

from hotlog import get_logger

from repolish.commands.apply.symlinks import apply_copies, apply_symlinks
from repolish.commands.apply.utils import chdir
from repolish.config import (
    ProviderConfig,
    RepolishConfigFile,
    load_config_file,
)
from repolish.config.resolution import resolve_config
from repolish.config.topology import (
    detect_workspace,
    detect_workspace_from_config,
)
from repolish.console import console
from repolish.linker.health import (
    ProviderReadinessResult,
    ensure_providers_ready,
)
from repolish.linker.orchestrator import (
    collect_provider_copies,
    collect_provider_symlinks,
)
from repolish.providers.models.context import WorkspaceContext
from repolish.reporting import print_summary_trees
from repolish.reporting.leaves import render_session_groups
from repolish.summaries import (
    LinkResult,
    link_copy_rows,
    link_symlink_rows,
)

logger = get_logger(__name__)


def _print_link_summaries(
    sections: list[tuple[str, LinkResult]],
) -> None:
    """Print the link and copy summary trees, each only if it has rows.

    The trees are two views over the same sections: `link_symlink_rows`
    derives the symlink rows, `link_copy_rows` the copy rows with their
    pause state. Empty views render nothing, so runs without symlinks or
    without copies stay silent for that tree.
    """
    print_summary_trees(
        [
            (
                'link summary',
                render_session_groups(link_symlink_rows(sections)),
            ),
            ('copy summary', render_session_groups(link_copy_rows(sections))),
        ],
    )


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


def _format_provider_message(
    alias: str,
    provider_config: ProviderConfig,
    location_context: str | None = None,
) -> str:
    """Format a success message for a linked provider.

    Uses the alias (user-configured name) since that's how the user
    refers to the provider. Shows the resources directory path.
    In monorepo mode, the location context is appended.
    """
    if provider_config.cli:
        resources_dir = '.repolish/' + alias
    elif provider_config.provider_root:
        resources_dir = str(provider_config.provider_root)
    else:
        # Unreachable: ProviderConfig validator requires provider_root when cli is absent
        resources_dir = alias  # pragma: no cover

    base_msg = f'- [bold cyan]{resources_dir}[/bold cyan] from [bold green]{alias}[/bold green] are now available'
    if location_context:
        return f'{base_msg} in "{location_context}"'
    return base_msg


def _print_link_success(
    result: ProviderReadinessResult,
    config: RepolishConfigFile,
    location_context: str | None = None,
) -> None:
    """Print success feedback for linked providers.

    Uses the same formatting as the provider CLI decorator for consistency.
    Cached providers show a brief '(cached)' indicator. CLI and static
    providers show the resources directory and provider alias.
    """
    for alias in result.cached:
        console.print(f'[dim]- {alias} (cached)[/dim]')

    for alias in result.ready:
        if alias not in result.cached:
            provider_config = config.providers.get(alias)
            if provider_config:
                msg = _format_provider_message(
                    alias,
                    provider_config,
                    location_context,
                )
                console.print(msg)


def _empty_link_result() -> LinkResult:
    """The handoff for a config with nothing to link."""
    return LinkResult(
        symlinks={},
        copies={},
        held_back={},
        paused_files=frozenset(),
    )


def _link_config(
    config_path: Path,
    mode: str = 'standalone',
    location_context: str | None = None,
    *,
    force: bool = False,
) -> tuple[int, LinkResult]:
    """Run ensure_providers_ready for the config at *config_path*.

    Returns (exit_code, LinkResult). The copy map is handed over
    unfiltered — paused targets stay in it so the summary tree can mark
    them, while ``apply_copies`` skips (and warns about) their
    materialisation and reports exactly which destinations were held
    back. ``paused_files`` rides along so a whole-target pause is
    detected even when nothing was held back.
    """
    config = load_config_file(config_path)
    if not config.providers:
        return 0, _empty_link_result()
    provider_names = _get_provider_names(config)
    logger.info('linking_providers', providers=provider_names, _display_level=1)
    result = ensure_providers_ready(
        provider_names,
        config.providers,
        config_path.resolve().parent,
        force=force,
        location_context=location_context,
        verify_locations=True,
    )
    if result.failed:
        logger.warning(
            'some_providers_not_linked',
            failed=result.failed,
            _display_level=1,
        )
        return 1, _empty_link_result()
    _print_link_success(result, config, location_context)
    resolved = resolve_config(config)
    resolved_symlinks = collect_provider_symlinks(
        resolved.providers,
        config.providers,
        mode=mode,
    )
    apply_symlinks(resolved_symlinks, resolved.providers)
    resolved_copies = collect_provider_copies(
        resolved.providers,
        config.providers,
        mode=mode,
    )
    paused_files = frozenset(resolved.paused_files)
    held_back = apply_copies(
        resolved_copies,
        resolved.providers,
        paused_files=paused_files,
    )
    return 0, LinkResult(
        symlinks=resolved_symlinks,
        copies=resolved_copies,
        held_back=held_back,
        paused_files=paused_files,
    )


def _detect_workspace(
    config: RepolishConfigFile,
    config_dir: Path,
) -> WorkspaceContext | None:
    if config.workspace and config.workspace.members:
        return detect_workspace_from_config(config_dir, config.workspace)
    return detect_workspace(config_dir)


def _link_members(
    mono_ctx: WorkspaceContext,
    config_dir: Path,
    *,
    force: bool = False,
) -> tuple[int, list[tuple[str, LinkResult]]]:
    """Link providers in every member directory.

    Returns (exit_code, sections). Each section is the member's label
    paired with its `LinkResult`, so the link and copy summary trees are
    both derived from the same sections and can mark paused (and
    partially paused) targets.
    """
    sections: list[tuple[str, LinkResult]] = []
    for m in mono_ctx.members:
        member_dir = (config_dir / m.path).resolve()
        member_config = member_dir / 'repolish.yaml'
        # pragma: no cover — detect_workspace_from_config already filters out members
        # without repolish.yaml via _build_member_info; this guard is a safety net only
        if not member_config.exists():  # pragma: no cover
            continue  # pragma: no cover
        logger.info('linking_member', member=m.name, _display_level=1)
        location_context = str(m.path)
        with chdir(member_dir):
            rc, result = _link_config(
                member_config,
                mode='member',
                location_context=location_context,
                force=force,
            )
        if rc != 0:
            return rc, sections
        if result.symlinks or result.copies:
            sections.append((f'Member: {m.name}', result))
    return 0, sections


def _command_monorepo(
    config_path: Path,
    config_dir: Path,
    mono_ctx: WorkspaceContext,
    *,
    force: bool = False,
) -> int:
    """Handle the monorepo case: link root and all members.

    Returns exit code (0 for success, 1 for failure).
    """
    console.print('[bold]Monorepo detected[/bold]')
    rc, root_result = _link_config(
        config_path,
        mode='root',
        location_context='root',
        force=force,
    )
    if rc != 0:
        return rc
    sections: list[tuple[str, LinkResult]] = []
    if root_result.symlinks or root_result.copies:
        sections.append(('Root', root_result))
    rc, member_sections = _link_members(
        mono_ctx,
        config_dir,
        force=force,
    )
    if rc != 0:
        return rc
    sections.extend(member_sections)
    _print_link_summaries(sections)
    return 0


def _command_standalone(config_path: Path, *, force: bool = False) -> int:
    """Handle the standalone case: link a single config.

    Returns exit code (0 for success, 1 for failure).
    """
    config = load_config_file(config_path)
    if not config.providers:
        logger.warning('no_providers_configured', _display_level=1)
        return 0
    rc, result = _link_config(
        config_path,
        mode='standalone',
        force=force,
    )
    if rc != 0:
        return rc
    _print_link_summaries([('Standalone', result)])
    return 0


def command(config_path: Path, *, force: bool = False) -> int:
    """Run repolish link with the given config.

    Args:
        config_path: Path to repolish.yaml
        force: If True, re-link all providers even if already linked.
            Default is False, which checks cache and only links if needed.
    """
    logger.info(
        'loading_config',
        config_file=str(config_path),
        _display_level=1,
    )
    config = load_config_file(config_path)
    config_dir = config_path.resolve().parent

    mono_ctx = _detect_workspace(config, config_dir)

    if mono_ctx is not None:
        return _command_monorepo(config_path, config_dir, mono_ctx, force=force)
    return _command_standalone(config_path, force=force)
