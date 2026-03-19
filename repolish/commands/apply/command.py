import json
from pathlib import Path

from hotlog import get_logger
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from repolish.builder import stage_templates
from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.commands.apply.pipeline import _ordered_aliases, resolve_session
from repolish.config import (
    ProviderSymlink,
    RepolishConfig,
    ResolvedProviderInfo,
)
from repolish.console import console
from repolish.hydration import (
    apply_generated_output,
    check_generated_output,
    prepare_staging,
    preprocess_templates,
    render_template,
    rich_print_diffs,
)
from repolish.linker.orchestrator import create_provider_symlinks
from repolish.loader.models import (
    GlobalContext,
    Providers,
    TemplateMapping,
    build_file_records,
    get_global_context,
)
from repolish.misc import ctx_to_dict
from repolish.utils import run_post_process
from repolish.version import __version__

logger = get_logger(__name__)


_MODE_STYLE: dict[str, str] = {
    'regular': 'green',
    'create_only': 'yellow',
    'delete': 'red',
    'keep': 'cyan',
}


def _collect_excluded_sources(
    file_mappings: dict[str, str | TemplateMapping],
) -> set[str]:
    """Collect all explicit source template paths from file_mappings.

    When a provider explicitly maps a source template via ``create_file_mappings``,
    that file should not also be auto-staged at its natural position in the
    provider's ``repolish/`` tree — the developer has already decided where it
    goes (possibly with a different destination name).
    """
    excluded: set[str] = set()
    for src in file_mappings.values():
        if isinstance(src, str):
            excluded.add(src)
        elif src.source_template is not None:
            excluded.add(src.source_template)
    return excluded


def _create_staged_template(
    setup_input: Path,
    config: RepolishConfig,
    excluded_sources: set[str] | None = None,
) -> dict[str, str]:
    """Build template directory list from `config` and create staging.

    This mirrors the previous inline logic in `command` but keeps the
    complexity outside of the top-level function.

    Returns:
        A mapping from merged-template-relative-path to the provider id that
        supplied it.  Tests previously patched `stage_templates`
        and expected no return value; to keep them working we normalise the
        result here.
    """
    template_dirs = _gather_template_directories(config)
    result = stage_templates(
        setup_input,
        template_dirs,
        template_overrides=config.template_overrides,
        excluded_sources=excluded_sources,
    )
    # result may be either Path (legacy) or (Path, sources) tuple
    if isinstance(result, tuple) and len(result) == 2:
        _, sources = result
    else:
        sources = {}
    return sources


def _gather_template_directories(
    config: RepolishConfig,
) -> list[Path | tuple[str | None, Path]]:
    """Return the template directories in the order they should be staged.

    Providers drive the result; the `directories` field no longer exists.
    If `providers_order` is given we honour it, otherwise we use dict key order.
    The return type now uses the same element-level union as
    :func:`stage_templates` so `ci-checks` won't complain about
    invariant lists.  Callers need not change.
    """
    # each entry may be a plain Path or an (alias, Path) pair
    template_dirs: list[Path | tuple[str | None, Path]] = []
    # build in-order list from providers
    order = config.providers_order or list(config.providers.keys())
    for alias in order:
        info = config.providers.get(alias)
        if info is None:
            continue
        path = info.provider_root
        template_dirs.append((alias, path))

    # if no alias information needed (only plain Paths or ``(None, path)``
    # pairs), convert everything to a simple list of directories.  we avoid
    # unpacking here because ``template_dirs`` may contain bare Path objects
    # once the element-level union type is in play.
    if not any(isinstance(entry, tuple) and entry[0] is not None for entry in template_dirs):
        return [entry if isinstance(entry, Path) else entry[1] for entry in template_dirs]

    return template_dirs



def _collect_provider_files(
    providers: Providers,
    alias: str,
) -> list[dict[str, str | None]]:
    """Return sorted list of {path, mode} for files this provider contributes."""
    return [
        {'path': r.path, 'mode': r.mode.value, 'source': r.source} for r in providers.file_records if r.owner == alias
    ]


def _build_provider_table(
    owner: str,
    records: list,
    owner_symlinks: list[ProviderSymlink],
) -> Table:
    """Build a Rich Table for one provider showing files and symlinks."""
    total = len(records) + len(owner_symlinks)
    title = f'{owner} ({total} file{"s" if total != 1 else ""})'
    table = Table(title=title, show_header=True, header_style='bold')
    table.add_column('Mode', style='dim', no_wrap=True)
    table.add_column('Path')
    table.add_column('Source', style='dim')
    for record in records:
        mode_val = record.mode.value
        style = _MODE_STYLE.get(mode_val, '')
        source = record.source if record.source and record.source != record.path else ''
        table.add_row(f'[{style}]{mode_val}[/{style}]', record.path, source)
    for sl in owner_symlinks:
        table.add_row('[blue]symlink[/blue]', str(sl.target), str(sl.source))
    return table


def _print_files_summary(
    providers: Providers,
    symlinks: dict[str, list[ProviderSymlink]] | None = None,
) -> None:
    """Print one Rich table per provider alias showing mode and path for each file."""
    by_owner: dict[str, list] = {}
    for record in providers.file_records:
        by_owner.setdefault(record.owner, []).append(record)

    _syms = symlinks if symlinks is not None else {}
    all_owners = list(by_owner.keys())
    for alias in _syms:
        if alias not in all_owners:
            all_owners.append(alias)

    for owner in all_owners:
        console.print(
            _build_provider_table(
                owner,
                by_owner.get(owner, []),
                _syms.get(owner, []),
            ),
        )


def _check_one_symlink(
    alias: str,
    symlink: ProviderSymlink,
    source_path: Path,
) -> str | None:
    """Return an issue string if the symlink is wrong/missing, else None."""
    target_path = Path(symlink.target)
    if target_path.is_symlink():
        actual = target_path.readlink().resolve()
        if actual != source_path:
            return f'{alias}: symlink {symlink.target!s} → {actual!s} (expected → {source_path!s})'
        return None
    if target_path.exists():
        return f'{alias}: {symlink.target!s} exists but is not a symlink'
    return f'{alias}: missing symlink {symlink.target!s} → {symlink.source!s}'


def _check_symlinks(
    resolved_symlinks: dict[str, list[ProviderSymlink]],
    providers: dict[str, ResolvedProviderInfo],
) -> list[str]:
    """Return a list of symlink issues (empty if all expected symlinks are correct)."""
    issues: list[str] = []
    for alias, symlinks in resolved_symlinks.items():
        info = providers.get(alias)
        if info is None:  # pragma: no cover - resolved_symlinks and providers share the same source dict
            continue
        for symlink in symlinks:
            source_path = (info.resources_dir / symlink.source).resolve()
            issue = _check_one_symlink(alias, symlink, source_path)
            if issue is not None:
                issues.append(issue)
    return issues


def _render_templates(
    setup_input: Path,
    providers: Providers,
    setup_output: Path,
) -> int:
    """Render templates; return 1 on error, 0 on success."""
    try:
        render_template(setup_input, providers, setup_output)
    except RuntimeError as exc:
        errors = [line for line in str(exc).splitlines() if line and not line.endswith(':')]
        logger.exception('render_failed', errors=errors)
        return 1
    return 0


def _apply_symlinks(
    resolved_symlinks: dict[str, list[ProviderSymlink]],
    providers: dict[str, ResolvedProviderInfo],
) -> None:
    """Materialise all resolved symlinks for every provider."""
    for alias, symlinks in resolved_symlinks.items():
        info = providers.get(alias)
        if info:
            create_provider_symlinks(alias, info.resources_dir, symlinks)


def _build_provider_panel(
    alias: str,
    ctx: object,
    records: list,
    owner_symlinks: list[ProviderSymlink],
    role_label: str,
) -> Panel:
    """Build a Rich Panel for one provider with property, context, and files sections."""
    props = Table.grid(padding=(0, 1))
    props.add_column(style='bold cyan', no_wrap=True)
    props.add_column()
    props.add_row('name', alias)
    props.add_row('role', role_label)

    ctx_dict = ctx_to_dict(ctx) if ctx is not None else {}
    ctx_display = {k: v for k, v in ctx_dict.items() if k not in ('repolish', '_provider')}
    if ctx_display:
        ctx_table = Table.grid(padding=(0, 1))
        ctx_table.add_column(style='dim', no_wrap=True)
        ctx_table.add_column()
        for k, v in ctx_display.items():
            ctx_table.add_row(str(k), str(v))
    else:
        ctx_table = Text('(no context fields)', style='dim')

    total = len(records) + len(owner_symlinks)
    if total:
        files_table = Table(
            show_header=True,
            header_style='bold',
            box=None,
            padding=(0, 1),
        )
        files_table.add_column('Mode', style='dim', no_wrap=True)
        files_table.add_column('Path')
        files_table.add_column('Source', style='dim')
        for record in records:
            mode_val = record.mode.value
            style = _MODE_STYLE.get(mode_val, '')
            source = record.source if record.source and record.source != record.path else ''
            files_table.add_row(
                f'[{style}]{mode_val}[/{style}]',
                record.path,
                source,
            )
        for sl in owner_symlinks:
            files_table.add_row(
                '[blue]symlink[/blue]',
                str(sl.target),
                str(sl.source),
            )
    else:
        files_table = Text('(no files)', style='dim')

    from rich.console import Group  # noqa: PLC0415
    from rich.rule import Rule  # noqa: PLC0415

    body = Group(
        props,
        Rule(style='dim'),
        Text('context', style='bold'),
        ctx_table,
        Rule(style='dim'),
        Text(f'files ({total})', style='bold'),
        files_table,
    )
    return Panel(body, title=f'[bold]{alias}[/bold]', border_style='cyan')


def _role_label(ctx: object) -> str:
    """Return a display label for the provider's monorepo role."""
    try:
        from repolish.loader.models import BaseContext  # noqa: PLC0415

        if isinstance(ctx, BaseContext):
            info = ctx._provider.monorepo
            if info.mode == 'root':
                return 'root'
            if info.mode == 'package' and info.member_name:
                return f'package: {info.member_name}'
    except Exception:  # noqa: BLE001
        pass
    return 'standalone'


def _print_provider_panels(
    providers: Providers,
    aliases: list[str],
    alias_to_pid: dict[str, str],
    resolved_symlinks: dict[str, list[ProviderSymlink]],
) -> None:
    """Print Rich panels for all providers, grouped by monorepo role."""
    from rich.rule import Rule  # noqa: PLC0415

    by_owner: dict[str, list] = {}
    for record in providers.file_records:
        by_owner.setdefault(record.owner, []).append(record)

    _syms = resolved_symlinks or {}

    # separate root providers from package-member providers and standalone
    root_aliases: list[str] = []
    member_aliases: dict[str, list[str]] = {}  # member_name -> [alias, ...]
    standalone_aliases: list[str] = []

    for alias in aliases:
        pid = alias_to_pid.get(alias)
        ctx = providers.provider_contexts.get(pid) if pid else None
        label = _role_label(ctx)
        if label == 'root':
            root_aliases.append(alias)
        elif label.startswith('package:'):
            member_name = label[len('package: ') :]
            member_aliases.setdefault(member_name, []).append(alias)
        else:
            standalone_aliases.append(alias)

    def _emit(group_title: str, group_aliases: list[str]) -> None:
        console.print(Rule(f'[bold]{group_title}[/bold]', style='bright_black'))
        for a in group_aliases:
            pid = alias_to_pid.get(a)
            ctx = providers.provider_contexts.get(pid) if pid else None
            label = _role_label(ctx)
            panel = _build_provider_panel(
                a,
                ctx,
                by_owner.get(a, []),
                _syms.get(a, []),
                label,
            )
            console.print(panel)

    if root_aliases:
        _emit('Root', root_aliases)
    for member_name, m_aliases in member_aliases.items():
        _emit(f'Member: {member_name}', m_aliases)
    if standalone_aliases:
        _emit('Standalone', standalone_aliases)


def _log_providers_summary(
    providers: Providers,
    aliases: list[str],
    alias_to_pid: dict[str, str],
    resolved_symlinks: dict[str, list[ProviderSymlink]],
    global_context: GlobalContext | None = None,
) -> None:
    """Log global/per-provider context and print the provider panels."""
    ctx = global_context if global_context is not None else get_global_context()
    logger.info(
        'global_context',
        context={'repolish': ctx.model_dump()},
        note='available to all providers',
    )
    logger.info(
        'providers_context',
        providers=[
            {
                'alias': alias,
                'context': {
                    k: v
                    for k, v in ctx_to_dict(
                        providers.provider_contexts.get(alias_to_pid[alias]),
                    ).items()
                    if k != 'repolish'
                },
                'file_count': sum(1 for r in providers.file_records if r.owner == alias),
            }
            for alias in aliases
            if alias in alias_to_pid
        ],
    )
    _print_provider_panels(providers, aliases, alias_to_pid, resolved_symlinks)
    logger.info(
        'providers_ready',
        suggestion='see .repolish/_ for extra information on each provider',
    )


def _finish_check(  # noqa: PLR0913 - using helper function to reduce cognitive complexity of `command`
    setup_output: Path,
    providers: Providers,
    base_dir: Path,
    paused: frozenset[str],
    resolved_symlinks: dict[str, list[ProviderSymlink]],
    provider_infos: dict[str, ResolvedProviderInfo],
    *,
    disable_auto_staging: bool = False,
) -> int:
    """Run check mode: report diffs and symlink issues; return 2 if any, else 0."""
    diffs = check_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=paused,
        disable_auto_staging=disable_auto_staging,
    )
    symlink_issues = _check_symlinks(resolved_symlinks, provider_infos)
    if diffs:
        logger.error(
            'check_results',
            suggestion='run `repolish apply` to apply changes',
        )
        rich_print_diffs(diffs)
    if symlink_issues:
        logger.error(
            'symlink_check_failed',
            issues=symlink_issues,
            suggestion='run `repolish apply` to fix symlinks',
        )
    return 2 if (diffs or symlink_issues) else 0


def _debug_file_slug(ctx: object, alias: str) -> str:
    """Return a filename slug capturing monorepo role + provider alias.

    Examples::

        root.devkit-workspace
        pkg-alpha.devkit-python
        standalone.simple-provider
    """
    try:
        from repolish.loader.models import BaseContext  # noqa: PLC0415

        if isinstance(ctx, BaseContext):
            info = ctx._provider
            mode = info.monorepo.mode
            if mode == 'root':
                prefix = 'root'
            elif mode == 'package' and info.monorepo.member_name:
                prefix = info.monorepo.member_name
            else:
                prefix = 'standalone'
            return f'{prefix}.{alias}'
    except Exception:  # noqa: BLE001
        pass
    return f'standalone.{alias}'


def _write_provider_debug_files(
    base_dir: Path,
    config: RepolishConfig,
    providers: Providers,
    alias_to_pid: dict[str, str],
) -> None:
    """Write per-provider context and file decisions to .repolish/_/.

    Each provider gets a ``provider-context.<role>.<alias>.json`` file where
    ``role`` is ``root``, ``standalone``, or the member package name
    (e.g. ``pkg-alpha``).  Written after staging so ``template_sources`` is
    already populated.
    """
    debug_dir = base_dir / '.repolish' / '_'
    debug_dir.mkdir(parents=True, exist_ok=True)

    for alias in _ordered_aliases(config):
        pid = alias_to_pid.get(alias)
        if not pid:
            continue
        ctx = providers.provider_contexts.get(pid)
        slug = _debug_file_slug(ctx, alias)
        data: dict[str, object] = {
            'alias': alias,
            'context': ctx_to_dict(ctx),
            'files': _collect_provider_files(providers, alias),
        }
        out_path = debug_dir / f'provider-context.{slug}.json'
        out_path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding='utf-8',
        )


def apply_session(session: ResolvedSession, *, check_only: bool = False) -> int:
    """Run the apply/check pipeline for an already-resolved session.

    Performs staging, rendering, post-processing, then either checks for diffs
    (``check_only=True``) or writes changes to disk.

    Callers that sequence multiple sessions (e.g. ``coordinate_sessions``) call
    this after collecting all resolved sessions so they can inspect cross-session
    interactions before any files are written.
    """
    config = session.config
    providers = session.providers
    resolved_symlinks = session.resolved_symlinks
    alias_to_pid = session.alias_to_pid
    pid_to_alias = session.pid_to_alias
    aliases = session.aliases
    config_pid = config.config_dir.as_posix()

    logger.info('providers_loaded', providers=aliases)

    # staging must happen before we can report per-provider template ownership
    base_dir, setup_input, setup_output = prepare_staging(config)
    sources = _create_staged_template(
        setup_input,
        config,
        excluded_sources=_collect_excluded_sources(providers.file_mappings) | providers.suppressed_sources,
    )
    # stage_templates records alias as the provider id; provider_contexts is
    # keyed by the full directory path (pid).  Translate here so rendering
    # can look up the right context.
    providers.template_sources = {rel: alias_to_pid.get(alias, alias) for rel, alias in sources.items()}
    providers.file_records = build_file_records(
        providers,
        pid_to_alias,
        config_pid,
    )

    # write per-provider debug JSON to .repolish/_/provider-context.<alias>.json
    _write_provider_debug_files(
        base_dir,
        config,
        providers,
        alias_to_pid,
    )

    _log_providers_summary(
        providers,
        aliases,
        alias_to_pid,
        resolved_symlinks,
        session.global_context,
    )

    paused = frozenset(config.paused_files)
    if paused:
        logger.warning(
            'files_paused',
            files=sorted(paused),
            suggestion='remove entries from paused_files once the provider is fixed',
        )

    # Preprocess templates (anchor-driven replacements)
    preprocess_templates(setup_input, providers, base_dir)

    # Render templates using Jinja2
    if _render_templates(setup_input, providers, setup_output) != 0:
        return 1

    # Run any configured post-processing commands in the rendered output dir
    post_cwd = setup_output / 'repolish'
    run_post_process(config.post_process, post_cwd)

    is_root_pass = session.global_context.workspace.mode == 'root'
    if check_only:
        return _finish_check(
            setup_output,
            providers,
            base_dir,
            paused,
            resolved_symlinks,
            config.providers,
            disable_auto_staging=is_root_pass,
        )

    apply_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=paused,
        disable_auto_staging=is_root_pass,
    )
    _apply_symlinks(resolved_symlinks, config.providers)
    return 0


def run_session(options: ApplyOptions) -> int:
    """Run repolish for a single session.

    Resolves providers then applies changes (or checks for diffs when
    ``options.check_only`` is ``True``).  This is the entry point for
    standalone project runs; ``coordinate_sessions`` calls :func:`resolve_session`
    and :func:`apply_session` directly to gain visibility into all sessions
    before any files are written.
    """
    logger.info('repolish_started', version=__version__)
    session = resolve_session(options)
    return apply_session(session, check_only=options.check_only)
