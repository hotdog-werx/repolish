from pathlib import Path

from hotlog import get_logger

from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.config import RepolishConfig, load_config, load_config_file
from repolish.config.models.provider import (
    ProviderConfig,
    ProviderCopy,
    ProviderOverrides,
)
from repolish.fastlane import merge_fast_lanes, restrict_to_lane
from repolish.hydration import build_final_providers
from repolish.linker.health import ensure_providers_ready
from repolish.linker.orchestrator import (
    collect_provider_copies,
    collect_provider_symlinks,
)
from repolish.phases import PhaseTimer
from repolish.providers.models import (
    BaseInputs,
    FastLaneSpec,
    GlobalContext,
    ProviderEntry,
    get_global_context,
)
from repolish.providers.models.pipeline import ProviderContributions
from repolish.providers.orchestrator import create_providers

logger = get_logger(__name__)


def _alias_pid_maps(
    config: RepolishConfig,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (alias→pid, pid→alias) maps built from config.providers."""
    alias_to_pid = {alias: info.provider_root.as_posix() for alias, info in config.providers.items()}
    return alias_to_pid, {v: k for k, v in alias_to_pid.items()}


def _ordered_aliases(config: RepolishConfig) -> list[str]:
    """Return provider aliases in the configured or default order."""
    return config.providers_order or list(config.providers.keys())


def _build_provider_overrides(
    config: RepolishConfig,
    alias_to_pid: dict[str, str],
) -> dict[str, ProviderOverrides]:
    """Build provider overrides keyed by provider id using the typed config model."""
    provider_overrides: dict[str, ProviderOverrides] = {}
    for alias, info in config.providers.items():
        pid = alias_to_pid.get(alias, info.provider_root.as_posix())
        overrides = info.overrides
        if not overrides:
            continue
        provider_overrides[pid] = ProviderOverrides(
            context_merge=overrides.context_merge,
            context_dotted=overrides.context_dotted,
            anchors=overrides.anchors,
            file_mappings=overrides.file_mappings,
            copies=overrides.copies,
            validators=overrides.validators,
            insertions=overrides.insertions,
            insertions_extend_files=overrides.insertions_extend_files,
        )
    return provider_overrides


def _collect_session_outputs(
    config: RepolishConfig,
    alias_to_pid: dict[str, str],
    global_context: GlobalContext | None,
) -> tuple[list[ProviderEntry], list[BaseInputs]]:
    """Run a dry provider pass to capture this session's outward cross-session data.

    Returns ``(provider_entries, emitted_inputs)`` — the provider entries list
    and inputs emitted before routing.  These are forwarded to the root session
    as ``extra_provider_entries`` and ``extra_inputs`` so root providers see a
    complete picture of each member's contributions.
    """
    dirs: list[str | tuple[str, str]] = list(alias_to_pid.items())
    provider_overrides = _build_provider_overrides(config, alias_to_pid)

    # Build ProviderContributions from the already-typed per-provider overrides.
    contributions = ProviderContributions(
        overrides=dict(provider_overrides.items()),
    )

    dry = create_providers(
        dirs,
        contributions=contributions,
        global_context=global_context,
        dry_run=True,
    )
    return dry.all_providers_list, dry.emitted_inputs


def _load_session_config(
    options: ApplyOptions,
    config_dir: Path,
    timer: PhaseTimer,
) -> tuple[RepolishConfig, dict[str, ProviderConfig]]:
    """Read the config file and run the readiness check for a full session.

    Returns both the resolved config and the raw provider entries (what the
    symlink/copy collectors need). Readiness failures only warn: the
    providers in question are absent from the run, never fatal on their own.
    """
    with timer.phase('config_load'):
        raw_config = load_config_file(options.config_path)
        if options.provider_filter is not None:
            aliases = [
                alias
                for alias in (raw_config.providers_order or list(raw_config.providers.keys()))
                if alias in options.provider_filter
            ]
            filtered_raw_providers = {
                alias: raw_config.providers[alias] for alias in aliases if alias in raw_config.providers
            }
        else:
            aliases = raw_config.providers_order if raw_config.providers_order else list(raw_config.providers.keys())
            filtered_raw_providers = raw_config.providers
    with timer.phase('providers_ready'):
        readiness = ensure_providers_ready(
            aliases,
            filtered_raw_providers,
            config_dir,
            strict=options.strict,
            location_context=None,
        )
    if readiness.failed:
        logger.warning(
            'providers_not_ready',
            failed=readiness.failed,
            note='these providers will be absent from the run',
        )
    with timer.phase('config_load'):
        config = load_config(
            options.config_path,
            provider_filter=options.provider_filter,
        )
    return config, raw_config.providers


def _lane_copy_entries(
    spec: FastLaneSpec,
    pid_to_alias: dict[str, str],
    fallback_alias: str,
) -> dict[str, list[ProviderCopy]]:
    """Return the copy set *spec* declares, keyed by its provider alias.

    Normalization stamps every collected spec with its declaring provider's
    id, so the alias lookup resolves; the alias-empty case is a safety net
    for a spec that skipped normalization, and such a spec copies nothing.
    """
    alias = pid_to_alias.get(spec.source_provider or '') or fallback_alias
    if not spec.file_copies or not alias:
        return {}
    return {
        alias: [ProviderCopy(source=Path(copy.source), target=Path(copy.target)) for copy in spec.file_copies],
    }


def _lane_copies(
    spec: FastLaneSpec,
    pid_to_alias: dict[str, str],
    *,
    fallback_alias: str,
) -> dict[str, list[ProviderCopy]]:
    """Build the whole copy set for a lane run: the lane's own copies only."""
    return _lane_copy_entries(spec, pid_to_alias, fallback_alias)


def _fold_lane_copies(
    resolved_copies: dict[str, list[ProviderCopy]],
    specs: list[FastLaneSpec],
    pid_to_alias: dict[str, str],
) -> None:
    """Extend *resolved_copies* with what the merged lane specs declare.

    Full runs collect the provider's own copy set and the merged lanes' copies
    side by side, so a lane's copies materialize in a full apply exactly as
    they do when the lane runs alone.
    """
    for spec in specs:
        for alias, entries in _lane_copy_entries(
            spec,
            pid_to_alias,
            '',
        ).items():
            resolved_copies.setdefault(alias, []).extend(entries)


def resolve_session(options: ApplyOptions) -> ResolvedSession:
    """Run the provider pipeline and return a fully-resolved session snapshot.

    Loads configuration, ensures providers are ready, builds the provider
    pipeline (context creation -> input exchange -> finalization), and captures
    the result as a :class:`~repolish.commands.apply.options.ResolvedSession`.

    No files are written. The caller can use the returned object to drive the
    apply/check steps, or to pass cross-session data to a root session.
    """
    config_path = options.config_path
    config_dir = config_path.resolve().parent
    timer = PhaseTimer()

    if options.lane_config is not None:
        # Prepared lane run (repolish.fastlane.config): the provider's
        # location comes from its own package, so config resolution and
        # readiness registration are pure overhead here. Skip both.
        config = options.lane_config.config
        raw_providers = options.lane_config.raw_providers
    else:
        config, raw_providers = _load_session_config(options, config_dir, timer)

    effective_global_context = options.global_context or get_global_context()
    alias_to_pid, pid_to_alias = _alias_pid_maps(config)

    # Dry pass: capture what this session contributes outward for cross-session
    # routing (provider entries + emitted inputs before local consumption).
    # Single-provider standalone runs (fast lanes) never consume that data, so
    # they can skip the pass entirely.
    if options.skip_dry_pass:
        provider_entries, emitted_inputs = [], []
    else:
        with timer.phase('dry_pass'):
            provider_entries, emitted_inputs = _collect_session_outputs(
                config,
                alias_to_pid,
                effective_global_context,
            )

    with timer.phase('provider_pipeline'):
        providers = build_final_providers(
            config,
            global_context=effective_global_context,
            extra_provider_entries=options.extra_provider_entries,
            extra_inputs=options.extra_inputs,
        )
    resolved_symlinks = collect_provider_symlinks(
        config.providers,
        raw_providers,
        mode=effective_global_context.workspace.mode,
    )
    ordered_aliases = _ordered_aliases(config)

    # Fast lanes: fold every lane's contributions into the bundle (full runs)
    # or cut the bundle down to exactly one lane (lane runs). Both paths run
    # duplicate detection against the project's fast_lanes.resolutions.
    if options.lane is not None:
        # A lane run copies exactly what the lane declares in file_copies:
        # the provider's own copy set never collects (or executes) here.
        lane_spec = restrict_to_lane(
            providers,
            options.lane,
            resolutions=config.fast_lanes.resolutions,
            pid_to_alias=pid_to_alias,
        )
        resolved_copies = _lane_copies(
            lane_spec,
            pid_to_alias,
            fallback_alias=next(iter(config.providers), ''),
        )
    else:
        resolved_copies = collect_provider_copies(
            config.providers,
            raw_providers,
            mode=effective_global_context.workspace.mode,
        )
        _fold_lane_copies(
            resolved_copies,
            merge_fast_lanes(
                providers,
                resolutions=config.fast_lanes.resolutions,
                pid_to_alias=pid_to_alias,
            ),
            pid_to_alias,
        )

    return ResolvedSession(
        config_path=config_path,
        config=config,
        global_context=effective_global_context,
        providers=providers,
        aliases=ordered_aliases,
        provider_filter=options.provider_filter,
        alias_to_pid=alias_to_pid,
        pid_to_alias=pid_to_alias,
        resolved_symlinks=resolved_symlinks,
        resolved_copies=resolved_copies,
        extra_provider_entries=options.extra_provider_entries or [],
        extra_inputs=options.extra_inputs or [],
        provider_entries=provider_entries,
        emitted_inputs=emitted_inputs,
        phase_timer=timer,
    )
