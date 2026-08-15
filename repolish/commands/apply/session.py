from pathlib import Path

from hotlog import get_logger

from repolish.commands.apply.check import (
    CheckContext,
    finish_check,
    render_templates,
)
from repolish.commands.apply.debug import (
    write_file_context_debug_files,
    write_provider_debug_files,
)
from repolish.commands.apply.display import (
    print_summary_tree,
)
from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.commands.apply.pipeline import resolve_session
from repolish.commands.apply.staging import (
    create_staged_template,
)
from repolish.commands.apply.symlinks import apply_copies, apply_symlinks
from repolish.commands.apply.validators import _collect_file_validation_messages
from repolish.config.models.project import RepolishConfig
from repolish.hydration import (
    apply_generated_output,
    prepare_staging,
    preprocess_templates,
)
from repolish.hydration.mapping_resolution import resolve_mappings
from repolish.providers.models import SessionBundle, build_file_records
from repolish.providers.models.files import ValidationStatus
from repolish.utils import run_post_process
from repolish.version import __version__

logger = get_logger(__name__)


def _resolve_template_alias_map(
    sources: dict[str, str],
    alias_to_pid: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve staged template aliases to provider PIDs while preserving overlay metadata."""
    overlay_dirs: dict[str, str] = {}
    pid_map: dict[str, str] = {}
    for rel, raw_alias in sources.items():
        if ':' in raw_alias:
            base_alias, mode_suffix = raw_alias.split(':', 1)
            overlay_dirs[rel] = mode_suffix
        else:
            base_alias = raw_alias
        pid_map[rel] = alias_to_pid.get(base_alias, base_alias)
    return pid_map, overlay_dirs


def _write_debug_files(
    base_dir: Path,
    config: RepolishConfig,
    providers: SessionBundle,
    alias_to_pid: dict[str, str],
) -> None:
    """Write provider/file debug context JSON for troubleshooting and inspection."""
    write_provider_debug_files(
        base_dir,
        config,
        providers,
        alias_to_pid,
    )
    write_file_context_debug_files(
        base_dir,
        providers,
        alias_to_pid,
    )


def _log_paused_files(paused: frozenset[str]) -> None:
    """Emit a warning when any configured files are excluded from validation and apply."""
    if paused:
        logger.warning(
            'files_paused',
            files=sorted(paused),
            suggestion='remove entries from paused_files once the provider is fixed',
        )


def _run_post_process_if_needed(
    config: RepolishConfig,
    setup_output: Path,
    *,
    skip_post_process: bool,
) -> None:
    """Run configured post-processing only when a real rendered tree exists."""
    if not skip_post_process:
        post_cwd = setup_output / 'repolish'
        if post_cwd.exists() and any(post_cwd.iterdir()):
            run_post_process(config.post_process, post_cwd)


def _strict_validation_failed(session: ResolvedSession) -> bool:
    """Return whether strict mode should fail because any validator reported non-pass."""
    return any(
        result.status != ValidationStatus.PASS
        for by_name in session.validation_results.values()
        for result in by_name.values()
    )


def apply_session(
    session: ResolvedSession,
    *,
    check_only: bool = False,
    skip_post_process: bool = False,
    strict: bool = False,
) -> int:
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
    config_pid = config.config_dir.as_posix()
    mapped_sources = resolve_mappings(providers).mapped_sources

    # staging must happen before we can report per-provider template ownership
    base_dir, setup_input, setup_output = prepare_staging(config)
    sources = create_staged_template(
        setup_input,
        config,
        mapped_sources=(mapped_sources | providers.suppressed_sources),
        workspace_mode=session.global_context.workspace.mode,
    )
    providers.template_sources, providers.template_overlay_dirs = _resolve_template_alias_map(
        sources,
        alias_to_pid,
    )
    providers.file_records = build_file_records(
        providers,
        pid_to_alias,
        config_pid,
    )
    _write_debug_files(
        base_dir,
        config,
        providers,
        alias_to_pid,
    )

    paused = frozenset(config.paused_files)
    _log_paused_files(paused)
    providers.paused_files = paused

    # Preprocess templates (anchor-driven replacements)
    preprocess_templates(setup_input, providers, base_dir)

    # Render templates using Jinja2
    if render_templates(setup_input, providers, setup_output) != 0:
        return 1

    session.validation_results = _collect_file_validation_messages(
        providers,
        config.config_dir,
        setup_output / 'repolish',
    )
    _run_post_process_if_needed(
        config,
        setup_output,
        skip_post_process=skip_post_process,
    )

    is_root_pass = session.global_context.workspace.mode == 'root'
    if check_only:
        rc, check_result = finish_check(
            CheckContext(
                setup_output=setup_output,
                providers=providers,
                base_dir=base_dir,
                resolved_symlinks=resolved_symlinks,
                provider_infos=config.providers,
                disable_auto_staging=is_root_pass,
            ),
        )
        session.apply_result = check_result
        return rc

    session.apply_result = apply_generated_output(
        setup_output,
        providers,
        base_dir,
        disable_auto_staging=is_root_pass,
    )
    apply_symlinks(resolved_symlinks, config.providers)
    apply_copies(session.resolved_copies, config.providers)

    if strict and _strict_validation_failed(session):
        logger.error(
            'validators_failed',
            files=sorted(session.validation_results),
            validator_count=sum(len(v) for v in session.validation_results.values()),
        )
        return 1
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
    rc = apply_session(
        session,
        check_only=options.check_only,
        skip_post_process=options.skip_post_process,
        strict=options.strict,
    )
    print_summary_tree([session])
    return rc
