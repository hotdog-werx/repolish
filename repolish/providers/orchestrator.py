from collections.abc import Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

from repolish.phases import PhaseTimer
from repolish.providers import SessionBundle
from repolish.providers.context import _apply_provider_overrides
from repolish.providers.contributions import (
    collect_provider_contributions,
)
from repolish.providers.finalize import finalize_provider_contexts
from repolish.providers.inputs import (
    build_provider_metadata,
    collect_all_emitted_inputs,
    gather_received_inputs,
)
from repolish.providers.models import (
    Accumulators,
    BaseContext,
    BaseInputs,
    GlobalContext,
    Provider,
    ProviderEntry,
    get_global_context,
)
from repolish.providers.models.pipeline import (
    DryRunResult,
    PipelineOptions,
    ProviderContributions,
)
from repolish.providers.module import _load_module_cache
from repolish.providers.pipeline import (
    _build_all_providers_list,
    _populate_provider_context,
    _set_provider_basic_metadata,
    _set_provider_package_identity,
)


def _phase(options: PipelineOptions, name: str) -> AbstractContextManager[None]:
    """Return the configured timing context, or a no-op context."""
    return options.phase_timer.phase(name) if options.phase_timer else nullcontext()


@dataclass
class _PipelineState:
    """Provider-pipeline state prepared before selecting an execution path."""

    accumulators: Accumulators
    instances: list[Provider | None]
    all_providers: list[ProviderEntry]


def _prepare_pipeline_state(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    options: PipelineOptions,
) -> _PipelineState:
    """Build provider metadata, contexts, overrides, and the input registry."""
    accumulators = Accumulators()
    contributions = options.contributions
    accumulators.promoted_file_mappings.update(
        contributions.promoted_file_mappings,
    )
    accumulators.suppressed_sources.update(contributions.suppressed_sources)
    accumulators.file_validators.update(contributions.file_validators)
    accumulators.file_insertions.update(contributions.file_insertions)

    with _phase(options, 'provider_pipeline.instance_metadata'):
        instances = build_provider_metadata(module_cache)
        _set_provider_basic_metadata(
            module_cache,
            instances,
            options.alias_map or {},
        )

    with _phase(options, 'provider_pipeline.package_identity'):
        _set_provider_package_identity(
            module_cache,
            instances,
            options.provider_package_identity,
        )

    with _phase(options, 'provider_pipeline.contexts'):
        _populate_provider_context(
            module_cache,
            instances,
            provider_contexts,
            options.global_context,
        )

    with _phase(options, 'provider_pipeline.overrides'):
        for pid, overrides in contributions.overrides.items():
            if overrides.context_merge:
                _apply_provider_overrides(
                    provider_contexts,
                    {pid: overrides.context_merge},
                )
            if overrides.context_dotted:
                _apply_provider_overrides(
                    provider_contexts,
                    {pid: overrides.context_dotted},
                )

    with _phase(options, 'provider_pipeline.registry'):
        all_providers = _build_all_providers_list(
            module_cache,
            instances,
            provider_contexts,
            alias_map=options.alias_map,
        )
        if options.extra_provider_entries:
            all_providers += options.extra_provider_entries

    return _PipelineState(
        accumulators=accumulators,
        instances=instances,
        all_providers=all_providers,
    )


def _build_fast_path_bundle(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    state: _PipelineState,
    options: PipelineOptions,
) -> SessionBundle | None:
    """Return a reduced bundle for a command or named fast-lane run."""
    if options.context_only:
        return SessionBundle(provider_contexts=provider_contexts)

    if options.fast_lanes_only:
        with _phase(options, 'provider_pipeline.fast_lanes'):
            collect_provider_contributions(
                module_cache,
                provider_contexts,
                state.accumulators,
                contributions=options.contributions,
                fast_lanes_only=True,
            )
        return SessionBundle(
            provider_contexts=provider_contexts,
            fast_lanes=state.accumulators.fast_lanes,
            facet_owners=state.accumulators.facet_owners,
        )

    return None


def _run_standard_pipeline(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    state: _PipelineState,
    options: PipelineOptions,
) -> SessionBundle | DryRunResult:
    """Run input exchange, finalization, and ordinary contributions."""
    if options.dry_run:
        with _phase(options, 'provider_pipeline.emitted_inputs'):
            emitted = collect_all_emitted_inputs(
                module_cache,
                state.instances,
                provider_contexts,
                state.all_providers,
            )
        return DryRunResult(
            provider_contexts=provider_contexts,
            all_providers_list=state.all_providers,
            emitted_inputs=emitted,
        )

    with _phase(options, 'provider_pipeline.inputs'):
        received_inputs = gather_received_inputs(
            module_cache,
            state.instances,
            provider_contexts,
            state.all_providers,
            extra_inputs=options.extra_inputs,
        )

    with _phase(options, 'provider_pipeline.finalize'):
        finalize_provider_contexts(
            module_cache,
            state.instances,
            received_inputs,
            provider_contexts,
            state.all_providers,
            global_context=options.global_context,
        )

    with _phase(options, 'provider_pipeline.contributions'):
        collect_provider_contributions(
            module_cache,
            provider_contexts,
            state.accumulators,
            contributions=options.contributions,
        )

    accumulators = state.accumulators
    return SessionBundle(
        anchors=accumulators.merged_anchors,
        delete_files=list(accumulators.delete_set),
        file_mappings=accumulators.merged_file_mappings,
        create_only_files=list(accumulators.create_only_set),
        delete_history=accumulators.history,
        provider_contexts=provider_contexts,
        suppressed_sources=accumulators.suppressed_sources,
        disabled_file_mappings=accumulators.disabled_file_mappings,
        file_validators=accumulators.file_validators,
        validator_sources=accumulators.validator_sources,
        file_insertions=accumulators.file_insertions,
        insertion_registry=accumulators.insertion_registry,
        insertion_sources=accumulators.insertion_sources,
        promoted_file_mappings=accumulators.promoted_file_mappings,
        fast_lanes=accumulators.fast_lanes,
        facet_owners=accumulators.facet_owners,
    )


def _run_provider_pipeline(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    options: PipelineOptions | None = None,
) -> SessionBundle | DryRunResult:
    """Run the provider pipeline and return the final result.

    When ``options.dry_run`` is ``True``, the pipeline stops before
    ``collect_provider_contributions`` (no file writes) and returns a
    :class:`DryRunResult` containing the provider contexts, all-providers list,
    and raw emitted inputs.  All other cases return a :class:`SessionBundle` object
    as before.
    """
    _opts = options or PipelineOptions()
    state = _prepare_pipeline_state(module_cache, provider_contexts, _opts)

    fast_path_bundle = _build_fast_path_bundle(
        module_cache,
        provider_contexts,
        state,
        _opts,
    )
    if fast_path_bundle is not None:
        return fast_path_bundle
    return _run_standard_pipeline(module_cache, provider_contexts, state, _opts)


@overload
def create_providers(
    directories: Sequence[str | tuple[str, str]],
    *,
    contributions: ProviderContributions | None = ...,
    global_context: GlobalContext | None = ...,
    extra_provider_entries: list[ProviderEntry] | None = ...,
    extra_inputs: list[BaseInputs] | None = ...,
    dry_run: Literal[False] = ...,
    context_only: bool = ...,
    fast_lanes_only: bool = ...,
    phase_timer: PhaseTimer | None = ...,
    provider_package_identity: tuple[str, str] | None = ...,
) -> SessionBundle: ...


@overload
def create_providers(
    directories: Sequence[str | tuple[str, str]],
    *,
    contributions: ProviderContributions | None = ...,
    global_context: GlobalContext | None = ...,
    extra_provider_entries: list[ProviderEntry] | None = ...,
    extra_inputs: list[BaseInputs] | None = ...,
    dry_run: Literal[True],
    context_only: bool = ...,
    fast_lanes_only: bool = ...,
    phase_timer: PhaseTimer | None = ...,
    provider_package_identity: tuple[str, str] | None = ...,
) -> DryRunResult: ...


def create_providers(  # noqa: PLR0913 - skip for now
    directories: Sequence[str | tuple[str, str]],
    *,
    contributions: ProviderContributions | None = None,
    global_context: GlobalContext | None = None,
    extra_provider_entries: list[ProviderEntry] | None = None,
    extra_inputs: list[BaseInputs] | None = None,
    dry_run: bool = False,
    context_only: bool = False,
    fast_lanes_only: bool = False,
    phase_timer: PhaseTimer | None = None,
    provider_package_identity: tuple[str, str] | None = None,
) -> SessionBundle | DryRunResult:
    """Load all template providers and merge their contributions.

    Merging semantics:
    - context: dicts are merged in order; later providers override earlier keys.
    - anchors: dicts are merged in order; later providers override earlier keys.
    - file_mappings: dicts are merged in order; later providers override earlier keys.
    - create_only_files: lists are merged; later providers can add more files.
    - delete_files: providers supply Path entries; an entry prefixed with a
      leading '!' (literal leading char in the original string) will act as an
      undo for that path (i.e., prevent deletion). The loader will apply
      additions/removals in provider order.

    When *global_context* is ``None``, it is computed via :func:`get_global_context`.
    When *dry_run* is ``True``, returns a :class:`DryRunResult` instead of a
    :class:`SessionBundle` object.

    Use :class:`ProviderContributions` to pass per-provider overrides, anchors,
    and file mappings in a single consolidated container.
    """
    # Use the provided global context or compute it from git
    global_ctx_obj = global_context if global_context is not None else get_global_context()
    # Normalize input directories and build an alias map for configuration
    normalized_dirs: list[str] = []
    alias_map: dict[str, str] = {}

    for entry in directories:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            alias, path = entry
            path_str = Path(path).as_posix()
            normalized_dirs.append(path_str)
            alias_map[path_str] = alias
        else:
            path_str = Path(entry).as_posix()
            normalized_dirs.append(path_str)

    with _phase(
        PipelineOptions(phase_timer=phase_timer),
        'provider_pipeline.module_load',
    ):
        module_cache = _load_module_cache(normalized_dirs)
    provider_contexts: dict[str, BaseContext] = {}

    return _run_provider_pipeline(
        module_cache,
        provider_contexts,
        PipelineOptions(
            global_context=global_ctx_obj,
            contributions=contributions or ProviderContributions(),
            alias_map=alias_map,
            dry_run=dry_run,
            context_only=context_only,
            fast_lanes_only=fast_lanes_only,
            phase_timer=phase_timer,
            provider_package_identity=provider_package_identity,
            extra_provider_entries=extra_provider_entries,
            extra_inputs=extra_inputs,
        ),
    )
