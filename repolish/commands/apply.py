import json
from collections import Counter
from pathlib import Path

from hotlog import get_logger
from rich.console import Console
from rich.table import Table

from repolish.builder import stage_templates
from repolish.config import RepolishConfig, load_config
from repolish.hydration import (
    apply_generated_output,
    build_final_providers,
    check_generated_output,
    prepare_staging,
    preprocess_templates,
    render_template,
    rich_print_diffs,
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
console = Console()

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
        path = info.target_dir
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
    alias_to_pid = {alias: info.target_dir.as_posix() for alias, info in config.providers.items()}
    return alias_to_pid, {v: k for k, v in alias_to_pid.items()}


def _ordered_aliases(config: RepolishConfig) -> list[str]:
    """Return provider aliases in the configured or default order."""
    return config.providers_order or list(config.providers.keys())


def _collect_provider_files(
    providers: Providers,
    alias: str,
) -> list[dict[str, str]]:
    """Return sorted list of {path, mode} for files this provider contributes."""
    return [{'path': r.path, 'mode': r.mode.value} for r in providers.file_records if r.owner == alias]


def _print_files_summary(providers: Providers) -> None:
    """Print one Rich table per provider alias showing mode and path for each file."""
    # Group records by owner, preserving sorted-path order (file_records is pre-sorted).
    by_owner: dict[str, list] = {}
    for record in providers.file_records:
        by_owner.setdefault(record.owner, []).append(record)

    for owner, records in by_owner.items():
        title = f'{owner} ({len(records)} file{"s" if len(records) != 1 else ""})'
        table = Table(title=title, show_header=True, header_style='bold')
        table.add_column('Mode', style='dim', no_wrap=True)
        table.add_column('Path')
        for record in records:
            mode_val = record.mode.value
            style = _MODE_STYLE.get(mode_val, '')
            table.add_row(f'[{style}]{mode_val}[/{style}]', record.path)
        console.print(table)


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


def command(config_path: Path, *, check_only: bool) -> int:
    """Run repolish with the given config and options."""
    logger.info('repolish_started', version=__version__)

    config = load_config(config_path)
    providers = build_final_providers(config)
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

    # global context is the same for every provider — log it once
    logger.info(
        'global_context',
        context={'repolish': get_global_context().model_dump()},
        note='available to all providers',
    )

    # per-provider: typed context (repolish key omitted — see global_context) + file count
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
    # global cross-provider file ownership summary printed as rich tables
    _mode_counts = Counter(r.mode.value for r in providers.file_records)
    _owner_counts = Counter(r.owner for r in providers.file_records)
    logger.info(
        'files_summary',
        total=len(providers.file_records),
        by_mode=dict(_mode_counts),
        by_owner=dict(_owner_counts),
    )
    _print_files_summary(providers)
    logger.info(
        'providers_ready',
        suggestion='see .repolish/_ for extra information on each provider',
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
    render_error: str | None = None
    try:
        render_template(setup_input, providers, setup_output)
    except RuntimeError as exc:
        render_error = str(exc)
    if render_error is not None:
        errors = [line for line in render_error.splitlines() if line and not line.endswith(':')]
        logger.error('render_failed', errors=errors)
        return 1

    # Run any configured post-processing commands in the rendered output dir
    post_cwd = setup_output / 'repolish'
    run_post_process(config.post_process, post_cwd)

    if check_only:
        diffs = check_generated_output(
            setup_output,
            providers,
            base_dir,
            paused_files=paused,
        )
        if diffs:
            logger.error(
                'check_results',
                suggestion='run `repolish apply` to apply changes',
            )
            rich_print_diffs(diffs)
        return 2 if diffs else 0

    apply_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=paused,
    )
    return 0
