from pathlib import Path
from time import perf_counter

from hotlog import get_logger

from repolish.commands.apply.symlinks import apply_copies, apply_symlinks
from repolish.commands.apply.utils import chdir
from repolish.config import (
    ModuleProviderConfig,
    ProviderConfig,
    RepolishConfigFile,
    load_config_file,
)
from repolish.config.providers import load_provider_info
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
from repolish.phases import PhaseTimer
from repolish.providers.models.context import WorkspaceContext
from repolish.reporting import print_command_timings, print_summary_trees
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


def _linked_path(alias: str, config_dir: Path) -> str:
    """Return the directory *alias* actually linked to, for display.

    Reads the provider-info written at registration so the message always
    names the real directory (the module name under ``module_links``, the
    distribution or provider root otherwise) instead of guessing from the
    config shape. Falls back to the alias when no info exists.
    """
    info = load_provider_info(alias, config_dir)
    if info is None:  # pragma: no cover - readiness guarantees the info exists
        return f'.repolish/{alias}'
    resources = Path(info.resources_dir)
    # The recorded path is tried as-is before resolving: a module provider's
    # .repolish/ entry is a symlink into the package, and resolving it lands
    # outside the repo, which would defeat the relativization.
    for candidate in (resources, resources.resolve()):
        try:
            return candidate.relative_to(config_dir).as_posix()
        except ValueError:
            continue
    return str(resources)


def _format_provider_message(
    alias: str,
    config_dir: Path,
    location_context: str | None = None,
    *,
    cached: bool = False,
) -> str:
    """Format link feedback for one provider.

    Names the directory the provider actually linked to and the alias the
    user configured it under; cached providers show a '(cached)' indicator
    so a run reports what is linked, not just what changed. In monorepo
    mode, the location context is appended.
    """
    linked = _linked_path(alias, config_dir)
    base = f'- [bold cyan]{linked}[/bold cyan] from [bold green]{alias}[/bold green]'
    msg = f'{base} (cached)' if cached else f'{base} are now available'
    if location_context:
        return f'{msg} in "{location_context}"'
    return msg


def _print_link_success(
    result: ProviderReadinessResult,
    config_dir: Path,
    location_context: str | None = None,
) -> None:
    """Print success feedback for linked providers.

    Cached providers first, then freshly linked ones; both name the linked
    directory so the run tells the user what is in place, not only what
    changed.
    """
    for alias in result.cached:
        console.print(
            _format_provider_message(
                alias,
                config_dir,
                location_context,
                cached=True,
            ),
        )

    for alias in result.ready:
        if alias not in result.cached:
            console.print(
                _format_provider_message(alias, config_dir, location_context),
            )


def _empty_link_result() -> LinkResult:
    """The handoff for a config with nothing to link."""
    return LinkResult(
        symlinks={},
        copies={},
        held_back={},
        paused_files=frozenset(),
    )


def _filter_config(
    config: RepolishConfigFile,
    alias: str,
) -> RepolishConfigFile:
    """Return a copy of *config* containing only provider *alias*.

    Mirrors the filter in `config.loader.load_config`: the providers dict is
    reduced to the alias and `providers_order` is filtered to match.
    `model_copy` skips validators, which is what we want here — the full
    config was already validated at load time. An absent alias yields an
    empty-providers copy, which callers treat as "nothing to link here".
    """
    entry = config.providers.get(alias)
    if entry is None:
        return config.model_copy(
            update={'providers': {}, 'providers_order': []},
        )
    order = [a for a in (config.providers_order or []) if a == alias] or [alias]
    return config.model_copy(
        update={'providers': {alias: entry}, 'providers_order': order},
    )


def _synthesize_one_off_config(
    alias: str,
    module: str,
    base: RepolishConfigFile | None,
    config_path: Path,
) -> RepolishConfigFile:
    """Build a single-module config for `repolish link <alias> <module>`.

    The explicit pair is the whole provider selection, so only project-level
    link settings carry over from *base* (the loaded project config, or None
    with --no-config): `module_links` and `paused_files`. `template_overrides`
    is deliberately not carried over — its validator would reject the aliases
    it references, which the one-off config does not declare. Without a base
    config the entry defaults to module-style naming, so a no-config one-off
    links under the dashed module name regardless of distribution metadata.
    """
    config = RepolishConfigFile(
        providers={
            alias: ProviderConfig(module=ModuleProviderConfig(name=module)),
        },
        module_links=True if base is None else base.module_links,
        paused_files=list(base.paused_files) if base else [],
    )
    config.config_file = config_path
    return config


def _validate_targeted_args(
    alias: str | None,
    module: str | None,
    *,
    no_config: bool,
) -> str | None:
    """Return an error message when the targeted-link combination is invalid."""
    if module is not None and alias is None:
        return 'MODULE requires ALIAS: use `repolish link <alias> <module>`'
    if no_config and (alias is None or module is None):
        return '--no-config requires an ALIAS and MODULE pair; nothing would be linkable'
    return None


def _declared_aliases(
    config: RepolishConfigFile,
    mono_ctx: WorkspaceContext | None,
) -> list[str]:
    """All aliases a targeted link may select: root config plus member configs."""
    aliases = set(config.providers)
    if mono_ctx is not None:
        for member in mono_ctx.members:
            aliases.update(member.provider_aliases)
    return sorted(aliases)


def _link_config(  # noqa: PLR0913 - forwards the _link_loaded_config parameter set
    config_path: Path,
    mode: str = 'standalone',
    location_context: str | None = None,
    *,
    force: bool = False,
    timer: PhaseTimer,
    register_only: bool = False,
    provider_filter: str | None = None,
) -> tuple[int, LinkResult]:
    """Load the config at *config_path*, apply *provider_filter*, and link.

    When *provider_filter* is set only that alias is linked; a config without
    the alias links nothing (the skip is logged at debug level so monorepo
    members without the selection stay traceable).
    """
    config = load_config_file(config_path)
    if provider_filter is not None:
        config = _filter_config(config, provider_filter)
        if not config.providers:
            logger.debug(
                'link_alias_absent',
                alias=provider_filter,
                location=location_context,
            )
    return _link_loaded_config(
        config,
        mode=mode,
        location_context=location_context,
        force=force,
        timer=timer,
        register_only=register_only,
    )


def _link_loaded_config(  # noqa: PLR0913 - phase flags ride along with the config object
    config: RepolishConfigFile,
    mode: str = 'standalone',
    location_context: str | None = None,
    *,
    force: bool = False,
    timer: PhaseTimer,
    register_only: bool = False,
) -> tuple[int, LinkResult]:
    """Run the link phases for an already-loaded (or synthesized) *config*.

    Returns (exit_code, LinkResult). The copy map is handed over
    unfiltered — paused targets stay in it so the summary tree can mark
    them, while ``apply_copies`` skips (and warns about) their
    materialisation and reports exactly which destinations were held
    back. ``paused_files`` rides along so a whole-target pause is
    detected even when nothing was held back.

    Phase durations (register, resolve, symlinks, copies) are recorded on
    *timer* so the command footer can report them per section. With
    *register_only* the run stops after registration: resolve, symlinks
    and copies are skipped, leaving only the .repolish/ resource link
    and the provider info.
    """
    config_path = config.config_file
    if config_path is None:  # pragma: no cover - loader and synthesize both set it
        msg = 'config_file must be set before linking'
        raise ValueError(msg)
    if not config.providers:
        return 0, _empty_link_result()
    provider_names = _get_provider_names(config)
    logger.info('linking_providers', providers=provider_names, _display_level=1)
    with timer.phase('register'):
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
    _print_link_success(result, config_path.resolve().parent, location_context)
    if register_only:
        return 0, _empty_link_result()
    with timer.phase('resolve'):
        resolved = resolve_config(config)
    with timer.phase('symlinks'):
        resolved_symlinks = collect_provider_symlinks(
            resolved.providers,
            config.providers,
            mode=mode,
        )
        apply_symlinks(resolved_symlinks, resolved.providers)
    with timer.phase('copies'):
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
    register_only: bool = False,
    provider_filter: str | None = None,
) -> tuple[int, list[tuple[str, LinkResult]], list[tuple[str, PhaseTimer]]]:
    """Link providers in every member directory.

    Returns (exit_code, sections, session_timings). Each section is the
    member's label paired with its `LinkResult`, so the link and copy
    summary trees are both derived from the same sections and can mark
    paused (and partially paused) targets. *session_timings* pairs the
    same labels with each member's `PhaseTimer` for the run footer.
    """
    sections: list[tuple[str, LinkResult]] = []
    session_timings: list[tuple[str, PhaseTimer]] = []
    for m in mono_ctx.members:
        member_dir = (config_dir / m.path).resolve()
        member_config = member_dir / 'repolish.yaml'
        # pragma: no cover — detect_workspace_from_config already filters out members
        # without repolish.yaml via _build_member_info; this guard is a safety net only
        if not member_config.exists():  # pragma: no cover
            continue  # pragma: no cover
        logger.info('linking_member', member=m.name, _display_level=1)
        location_context = str(m.path)
        timer = PhaseTimer()
        session_timings.append((f'Member: {m.name}', timer))
        with chdir(member_dir):
            rc, result = _link_config(
                member_config,
                mode='member',
                location_context=location_context,
                force=force,
                timer=timer,
                register_only=register_only,
                provider_filter=provider_filter,
            )
        if rc != 0:
            return rc, sections, session_timings
        if result.symlinks or result.copies:
            sections.append((f'Member: {m.name}', result))
    return 0, sections, session_timings


def _command_monorepo(  # noqa: PLR0913 - forwards the targeted-link flags
    config_path: Path,
    config_dir: Path,
    mono_ctx: WorkspaceContext,
    *,
    force: bool = False,
    register_only: bool = False,
    provider_filter: str | None = None,
) -> tuple[int, list[tuple[str, PhaseTimer]]]:
    """Handle the monorepo case: link root and all members.

    Returns the exit code and the per-section timings for the footer.
    """
    console.print('[bold]Monorepo detected[/bold]')
    root_timer = PhaseTimer()
    rc, root_result = _link_config(
        config_path,
        mode='root',
        location_context='root',
        force=force,
        timer=root_timer,
        register_only=register_only,
        provider_filter=provider_filter,
    )
    session_timings: list[tuple[str, PhaseTimer]] = [('Root', root_timer)]
    if rc != 0:
        return rc, session_timings
    sections: list[tuple[str, LinkResult]] = []
    if root_result.symlinks or root_result.copies:
        sections.append(('Root', root_result))
    rc, member_sections, member_timings = _link_members(
        mono_ctx,
        config_dir,
        force=force,
        register_only=register_only,
        provider_filter=provider_filter,
    )
    session_timings.extend(member_timings)
    if rc != 0:
        return rc, session_timings
    sections.extend(member_sections)
    _print_link_summaries(sections)
    return 0, session_timings


def _command_standalone(
    config_path: Path,
    *,
    force: bool = False,
    register_only: bool = False,
    provider_filter: str | None = None,
) -> tuple[int, list[tuple[str, PhaseTimer]]]:
    """Handle the standalone case: link a single config.

    Returns the exit code and the per-section timings for the footer.
    """
    config = load_config_file(config_path)
    timer = PhaseTimer()
    if not config.providers and provider_filter is None:
        logger.warning('no_providers_configured', _display_level=1)
        return 0, [('Standalone', timer)]
    rc, result = _link_config(
        config_path,
        mode='standalone',
        force=force,
        timer=timer,
        register_only=register_only,
        provider_filter=provider_filter,
    )
    if rc != 0:
        return rc, [('Standalone', timer)]
    _print_link_summaries([('Standalone', result)])
    return 0, [('Standalone', timer)]


def _command_one_off(  # noqa: PLR0913 - mirrors the link command's flag set
    config_path: Path,
    alias: str,
    module: str,
    *,
    force: bool = False,
    no_config: bool = False,
    register_only: bool = False,
) -> int:
    """Link *module* under *alias* as a one-off, standalone in the config dir.

    The config file is consulted only for project-level settings
    (`module_links`, `paused_files`), never for provider selection. An alias
    that exists in the config is refused unless *no_config* explicitly
    ignores it — a one-off never silently shadows a config entry.
    """
    started = perf_counter()
    config_dir = config_path.resolve().parent
    base: RepolishConfigFile | None = None
    if no_config:
        if config_path.exists():
            logger.info(
                'config_ignored_no_config',
                config_file=str(config_path),
                _display_level=1,
            )
    elif config_path.exists():
        base = load_config_file(config_path)
        if alias in base.providers:
            logger.error(
                'link: alias exists in the config; pass --no-config to ignore the config entry',
                alias=alias,
            )
            return 1
        if _detect_workspace(base, config_dir) is not None:
            logger.info('one_off_link_standalone', _display_level=1)
    config = _synthesize_one_off_config(alias, module, base, config_path)
    timer = PhaseTimer()
    rc, result = _link_loaded_config(
        config,
        mode='standalone',
        force=force,
        timer=timer,
        register_only=register_only,
    )
    _print_link_summaries([('Standalone', result)])
    print_command_timings(
        'link',
        (perf_counter() - started) * 1000,
        [('Standalone', timer)],
        config_dir,
    )
    return rc


def command(  # noqa: PLR0913 - public entry point; the targeted-link flags ride along
    config_path: Path,
    *,
    force: bool = False,
    alias: str | None = None,
    module: str | None = None,
    no_config: bool = False,
    register_only: bool = False,
) -> int:
    """Run repolish link with the given config.

    Args:
        config_path: Path to repolish.yaml
        force: If True, re-link all providers even if already linked.
            Default is False, which checks cache and only links if needed.
        alias: Link only the provider aliased thus in the config. With
            `module`, instead links that module under the alias as a
            one-off that does not require a config entry.
        module: Dotted module name for a one-off link under `alias`.
        no_config: Do not read the config file; requires the alias and
            module pair.
        register_only: Stop after registration; skip project-root
            symlinks and copies.
    """
    if error := _validate_targeted_args(alias, module, no_config=no_config):
        logger.error('link: invalid argument combination', reason=error)
        return 1
    started = perf_counter()
    if alias is not None and module is not None:
        return _command_one_off(
            config_path,
            alias,
            module,
            force=force,
            no_config=no_config,
            register_only=register_only,
        )
    logger.info(
        'loading_config',
        config_file=str(config_path),
        _display_level=1,
    )
    config = load_config_file(config_path)
    config_dir = config_path.resolve().parent

    mono_ctx = _detect_workspace(config, config_dir)

    if alias is not None and alias not in _declared_aliases(config, mono_ctx):
        logger.error(
            'link: unknown provider alias',
            alias=alias,
            valid=_declared_aliases(config, mono_ctx),
        )
        return 1

    if mono_ctx is not None:
        rc, session_timings = _command_monorepo(
            config_path,
            config_dir,
            mono_ctx,
            force=force,
            register_only=register_only,
            provider_filter=alias,
        )
    else:
        rc, session_timings = _command_standalone(
            config_path,
            force=force,
            register_only=register_only,
            provider_filter=alias,
        )
    print_command_timings(
        'link',
        (perf_counter() - started) * 1000,
        session_timings,
        config_dir,
    )
    return rc
