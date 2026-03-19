from hotlog import get_logger

from repolish.commands.apply.check import (
    CheckContext,
    _finish_check,
    _render_templates,
)
from repolish.commands.apply.debug import _write_provider_debug_files
from repolish.commands.apply.display import _log_providers_summary
from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.commands.apply.pipeline import resolve_session
from repolish.commands.apply.staging import (
    _collect_excluded_sources,
    _create_staged_template,
)
from repolish.commands.apply.symlinks import _apply_symlinks
from repolish.hydration import (
    apply_generated_output,
    prepare_staging,
    preprocess_templates,
)
from repolish.loader.models import build_file_records
from repolish.utils import run_post_process
from repolish.version import __version__

logger = get_logger(__name__)


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
            CheckContext(
                setup_output=setup_output,
                providers=providers,
                base_dir=base_dir,
                paused=paused,
                resolved_symlinks=resolved_symlinks,
                provider_infos=config.providers,
                disable_auto_staging=is_root_pass,
            ),
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
