import json
from collections import Counter
from pathlib import Path

from hotlog import get_logger
from rich.table import Table

from repolish.builder import stage_templates
from repolish.config import (
    ProviderSymlink,
    RepolishConfig,
    ResolvedProviderInfo,
    load_config,
    load_config_file,
)
from repolish.console import console
from repolish.hydration import (
    apply_generated_output,
    build_final_providers,
    check_generated_output,
    prepare_staging,
    preprocess_templates,
    render_template,
    rich_print_diffs,
)
from repolish.linker.health import ensure_providers_ready
from repolish.linker.orchestrator import (
    collect_provider_symlinks,
    create_provider_symlinks,
)
from repolish.loader.models import (
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


def _alias_pid_maps(
    config: RepolishConfig,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (alias→pid, pid→alias) maps built from config.providers."""
    alias_to_pid = {alias: info.provider_root.as_posix() for alias, info in config.providers.items()}
    return alias_to_pid, {v: k for k, v in alias_to_pid.items()}


def _ordered_aliases(config: RepolishConfig) -> list[str]:
    """Return provider aliases in the configured or default order."""
    return config.providers_order or list(config.providers.keys())


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


def _log_providers_summary(
    providers: Providers,
    aliases: list[str],
    alias_to_pid: dict[str, str],
    resolved_symlinks: dict[str, list[ProviderSymlink]],
) -> None:
    """Log global/per-provider context and print the files summary table."""
    logger.info(
        'global_context',
        context={'repolish': get_global_context().model_dump()},
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
    _mode_counts = Counter(r.mode.value for r in providers.file_records)
    _owner_counts = Counter(r.owner for r in providers.file_records)
    logger.info(
        'files_summary',
        total=len(providers.file_records),
        by_mode=dict(_mode_counts),
        by_owner=dict(_owner_counts),
    )
    _print_files_summary(providers, resolved_symlinks)
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
) -> int:
    """Run check mode: report diffs and symlink issues; return 2 if any, else 0."""
    diffs = check_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=paused,
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


def _write_provider_debug_files(
    base_dir: Path,
    config: RepolishConfig,
    providers: Providers,
    alias_to_pid: dict[str, str],
) -> None:
    """Write per-provider context and file decisions to .repolish/_/.

    Each provider gets a `provider-context.<alias>.json` file containing its
    typed context and the list of files it controls.  Written after staging so
    `template_sources` is already populated.
    """
    debug_dir = base_dir / '.repolish' / '_'
    debug_dir.mkdir(parents=True, exist_ok=True)

    for alias in _ordered_aliases(config):
        pid = alias_to_pid.get(alias)
        if not pid:
            continue
        ctx = providers.provider_contexts.get(pid)
        data: dict[str, object] = {
            'alias': alias,
            'context': ctx_to_dict(ctx),
            'files': _collect_provider_files(providers, alias),
        }
        out_path = debug_dir / f'provider-context.{alias}.json'
        out_path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding='utf-8',
        )


def command(
    config_path: Path,
    *,
    check_only: bool,
    strict: bool = False,
) -> int:
    """Run repolish with the given config and options."""
    logger.info('repolish_started', version=__version__)

    # Ensure all providers are registered before resolving the config.
    # This writes/repairs provider-info files so load_config can trust them.
    raw_config = load_config_file(config_path)
    config_dir = config_path.resolve().parent
    aliases = raw_config.providers_order if raw_config.providers_order else list(raw_config.providers.keys())
    readiness = ensure_providers_ready(
        aliases,
        raw_config.providers,
        config_dir,
        strict=strict,
    )
    if readiness.failed:
        logger.warning(
            'providers_not_ready',
            failed=readiness.failed,
            note='these providers will be absent from the run',
        )

    config = load_config(config_path)

    providers = build_final_providers(config)
    resolved_symlinks = collect_provider_symlinks(
        config.providers,
        raw_config.providers,
    )
    alias_to_pid, pid_to_alias = _alias_pid_maps(config)
    config_pid = config.config_dir.as_posix()
    aliases = _ordered_aliases(config)

    # earliest possible signal: which providers are in play
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

    _log_providers_summary(providers, aliases, alias_to_pid, resolved_symlinks)

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

    if check_only:
        return _finish_check(
            setup_output,
            providers,
            base_dir,
            paused,
            resolved_symlinks,
            config.providers,
        )

    apply_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=paused,
    )
    _apply_symlinks(resolved_symlinks, config.providers)
    return 0
