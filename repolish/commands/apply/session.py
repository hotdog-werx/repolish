from dataclasses import replace
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
    print_run_summary,
)
from repolish.commands.apply.insertions import (
    stage_registered_insertions,
)
from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.commands.apply.pipeline import resolve_session
from repolish.commands.apply.staging import (
    create_staged_template,
)
from repolish.commands.apply.symlinks import apply_copies, apply_symlinks
from repolish.commands.apply.validators import _collect_validation
from repolish.config.models.project import RepolishConfig
from repolish.directives import (
    DirectivePhase,
    FerriedItem,
    PhaseResult,
    run_phase,
)
from repolish.hydration import (
    apply_generated_output,
    prepare_staging,
    preprocess_templates,
    rendered_file_pairs,
)
from repolish.hydration.mapping_resolution import resolve_mappings
from repolish.insertions.adoption import adopt_local_insertion_markers
from repolish.postprocess.report import write_post_process_report
from repolish.postprocess.runner import run_post_process
from repolish.providers.models import SessionBundle, build_file_records
from repolish.providers.models.files import ValidationStatus
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
    session: ResolvedSession,
    setup_output: Path,
    *,
    skip_post_process: bool,
) -> bool:
    """Run configured post-processing only when a real rendered tree exists.

    Records the run and its report path on *session* (the summary tree links
    to the report). Returns whether the run failed — the caller then aborts
    before anything is copied out, so the project tree is never touched by a
    run whose post-process failed.
    """
    if skip_post_process:
        return False
    config = session.config
    post_cwd = setup_output / 'repolish'
    if not (post_cwd.exists() and any(post_cwd.iterdir())):
        return False
    run = run_post_process(config.post_process, post_cwd, config.config_dir)
    if not run.outcomes:
        return False
    report_path = config.config_dir / '.repolish' / '_' / 'post-process.txt'
    session.post_process_runs.append(('session', run))
    session.post_process_reports.append(report_path)
    return run.failed


def _write_post_process_reports(session: ResolvedSession) -> None:
    """Write the text report for every post-process run recorded on *session*."""
    for (_label, run), report_path in zip(
        session.post_process_runs,
        session.post_process_reports,
        strict=True,
    ):
        write_post_process_report(
            report_path,
            run,
            timings=session.phase_timer.section(),
        )


def _validation_has_errors(session: ResolvedSession) -> bool:
    """Return whether any validator reported an actual error."""
    return any(
        result.status == ValidationStatus.ERROR
        for by_name in session.validation_results.values()
        for result in by_name.values()
    )


def _validation_has_warnings(session: ResolvedSession) -> bool:
    """Return whether any validator reported a warning."""
    return any(
        result.status == ValidationStatus.WARNING
        for by_name in session.validation_results.values()
        for result in by_name.values()
    )


def _run_after_render_directives(
    setup_output: Path,
    base_dir: Path,
) -> PhaseResult:
    """Apply directives tagged with phase="after-render" on rendered output files.

    Pairing of rendered files to their local counterparts is owned by hydration
    (:func:`rendered_file_pairs`); the after-render traversal itself lives in
    the directives node (:func:`run_phase`). Insertion-marker adoption is
    wired explicitly as a post pass so the directives package stays free of
    insertions knowledge.

    Returns the phase result so the session can merge whatever families
    ferried past the phase (``PhaseResult.ferry``).
    """
    return run_phase(
        DirectivePhase.AFTER_RENDER,
        rendered_file_pairs(setup_output, base_dir),
        post_passes=[adopt_local_insertion_markers],
    )


def _merge_ferries(
    *phase_ferries: dict[str, tuple[FerriedItem, ...]],
) -> dict[str, tuple[FerriedItem, ...]]:
    """Union per-family ferry dicts from the directive phases, in phase order."""
    merged: dict[str, list[FerriedItem]] = {}
    for phase_ferry in phase_ferries:
        for family, items in phase_ferry.items():
            merged.setdefault(family, []).extend(items)
    return {family: tuple(items) for family, items in merged.items()}


def _relativize_ferry_dests(
    ferry: dict[str, tuple[FerriedItem, ...]],
    base_dir: Path,
) -> dict[str, tuple[FerriedItem, ...]]:
    """Rewrite each item's dest relative to *base_dir* when it lives under it.

    Dests outside *base_dir* (staged files whose pair had no local side) keep
    their original path — consumers decide what those mean.
    """

    def _relative(dest: str) -> str:
        try:
            return Path(dest).relative_to(base_dir).as_posix()
        except ValueError:
            return dest

    return {
        family: tuple(replace(item, dest=_relative(item.dest)) for item in items) for family, items in ferry.items()
    }


def apply_session(
    session: ResolvedSession,
    *,
    check_only: bool = False,
    skip_post_process: bool = False,
    fail_on_warnings: bool = False,
) -> int:
    """Run the apply/check pipeline for an already-resolved session.

    Performs staging, rendering, post-processing, then either checks for diffs
    (``check_only=True``) or writes changes to disk.

    Callers that sequence multiple sessions (e.g. ``coordinate_sessions``) call
    this after collecting all resolved sessions so they can inspect cross-session
    interactions before any files are written.
    """
    try:
        return _apply_session(
            session,
            check_only=check_only,
            skip_post_process=skip_post_process,
            fail_on_warnings=fail_on_warnings,
        )
    finally:
        session.phase_timer.emit()
        _write_post_process_reports(session)


def _apply_session(
    session: ResolvedSession,
    *,
    check_only: bool,
    skip_post_process: bool,
    fail_on_warnings: bool,
) -> int:
    """Apply pipeline body; :func:`apply_session` wraps this for finalization."""
    timer = session.phase_timer
    config = session.config
    providers = session.providers
    resolved_symlinks = session.resolved_symlinks
    alias_to_pid = session.alias_to_pid
    pid_to_alias = session.pid_to_alias
    config_pid = config.config_dir.as_posix()
    mapped_sources = resolve_mappings(providers).mapped_sources

    # staging must happen before we can report per-provider template ownership
    with timer.phase('staging'):
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
            base_dir,
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

    # Preprocess templates (anchor-driven replacements). The returned ferry
    # carries whatever directive families ferried past the pre-render phase.
    with timer.phase('preprocess'):
        pre_render_ferry = preprocess_templates(
            setup_input,
            providers,
            base_dir,
        )

    # Render templates using Jinja2
    with timer.phase('render'):
        render_failed = render_templates(setup_input, providers, setup_output) != 0
    if render_failed:
        return 1

    # Reconcile developer-owned content that is only discoverable after Jinja rendering
    # (for example, directives inside loop-generated sections).
    with timer.phase('directives'):
        after_render = _run_after_render_directives(setup_output, base_dir)

        # Deliver every family's ferried data to its consumers: merged across both
        # phases, dests relativized to the project root. Consumers (insertions,
        # validators, ...) read the families they know from `providers.ferry`.
        providers.ferry = _relativize_ferry_dests(
            _merge_ferries(pre_render_ferry, after_render.ferry),
            base_dir,
        )

    is_root_pass = session.global_context.workspace.mode == 'root'

    # Stage insertions into the render tree in both modes so check compares and
    # apply copy the identical content, then post-process the render tree
    # exactly once. The project tree is only ever touched by the final copy.
    with timer.phase('insertions'):
        (
            session.insertion_results,
            session.provider_insertion_results,
            staged_insertion_dests,
        ) = stage_registered_insertions(
            providers,
            base_dir,
            setup_output,
            pid_to_alias,
        )
    with timer.phase('post_process'):
        post_failed = _run_post_process_if_needed(
            session,
            setup_output,
            skip_post_process=skip_post_process,
        )
    if post_failed:
        logger.error(
            'post_process_run_failed',
            report=str(
                config.config_dir / '.repolish' / '_' / 'post-process.txt',
            ),
            note='see the post-process summary tree for per-command details',
        )
        return 1

    if check_only:
        # In check mode, we compare staged output against base_dir without modifying files.
        # Do NOT apply_generated_output here - that would overwrite local changes!
        with timer.phase('check'):
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

    # Copy the post-processed render tree out to the project. Post-process
    # runs before this copy, never after: formatting a tree that was already
    # copied leaves the project with unformatted content while check reports
    # drift against the formatted staged copy on every run.
    with timer.phase('apply_copy'):
        session.apply_result = apply_generated_output(
            setup_output,
            providers,
            base_dir,
            disable_auto_staging=is_root_pass,
            insertion_dests=staged_insertion_dests,
        )
    with timer.phase('symlinks'):
        apply_symlinks(resolved_symlinks, config.providers)
    with timer.phase('copies'):
        session.paused_copies = apply_copies(
            session.resolved_copies,
            config.providers,
            paused_files=providers.paused_files,
        )

    with timer.phase('validation'):
        session.validation_results, session.validation_reports = _collect_validation(
            providers,
            config.config_dir,
            setup_output / 'repolish',
            reports_dir=base_dir / '.repolish' / '_' / 'validators',
            pid_to_alias=pid_to_alias,
        )

    if _validation_has_errors(session):
        logger.error(
            'validators_failed',
            files=sorted(session.validation_results),
            validator_count=sum(len(v) for v in session.validation_results.values()),
        )
        return 1

    if fail_on_warnings and _validation_has_warnings(session):
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
        fail_on_warnings=options.fail_on_warnings,
    )
    print_run_summary([session])
    return rc
