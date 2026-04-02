from pathlib import Path
from typing import Literal, overload

from repolish.providers import SessionBundle
from repolish.providers.context import (
    _apply_overrides_to_provider_contexts,
    _apply_provider_overrides,
)
from repolish.providers.exchange import (
    build_provider_metadata,
    collect_all_emitted_inputs,
    collect_provider_contributions,
    finalize_provider_contexts,
    gather_received_inputs,
)
from repolish.providers.models import (
    Accumulators,
    BaseContext,
    BaseInputs,
    GlobalContext,
    ProviderEntry,
    get_global_context,
)
from repolish.providers.models.pipeline import DryRunResult, PipelineOptions
from repolish.providers.module import _load_module_cache
from repolish.providers.pipeline import (
    _build_all_providers_list,
    _populate_provider_context,
    _set_provider_metadata,
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
    accum = Accumulators()

    # gather metadata and basic helper structures
    instances = build_provider_metadata(module_cache)

    # set alias and version on every provider instance before any hooks
    # (including create_context) are called.
    _alias_map = {} if options is None or options.alias_map is None else options.alias_map
    _set_provider_metadata(module_cache, instances, _alias_map)

    global_context = options.global_context if options is not None else GlobalContext()
    _populate_provider_context(
        module_cache,
        instances,
        provider_contexts,
        global_context,
    )

    context_overrides = None if options is None else options.context_overrides
    provider_overrides = None if options is None else options.provider_overrides

    # apply any per-provider overrides now that each provider has a concrete
    # context object.  this ensures `provide_inputs` sees the patched values
    # even though the loader API only accepts global overrides.
    _apply_provider_overrides(provider_contexts, provider_overrides)

    # include each provider's declared input schema so that other providers can
    # inspect it when deciding what to emit.  We build the list via a
    # dedicated helper to keep this function's complexity low.
    all_providers_list: list[ProviderEntry] = _build_all_providers_list(
        module_cache,
        instances,
        provider_contexts,
        alias_map=options.alias_map if options is not None else None,
    )

    # Extend all_providers_list with member entries from a monorepo dry pass.
    # This makes member providers visible to root providers via `all_providers`.
    extra_entries = options.extra_provider_entries if options is not None else None
    if extra_entries:
        all_providers_list = all_providers_list + extra_entries

    # apply overrides before input gathering
    if context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            context_overrides,
        )

    dry_run = options is not None and options.dry_run
    extra_inputs: list[BaseInputs] | None = options.extra_inputs if options is not None else None

    if dry_run:
        # Collect raw emitted inputs without routing — return early.
        emitted = collect_all_emitted_inputs(
            module_cache,
            instances,
            provider_contexts,
            all_providers_list,
        )
        return DryRunResult(
            provider_contexts=provider_contexts,
            all_providers_list=all_providers_list,
            emitted_inputs=emitted,
        )

    # we no longer attempt to predict receivers; just call all providers
    # for their outgoing inputs and route them based on schemas.
    # extra_inputs from member dry passes are injected into the routing pool.
    received_inputs = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        extra_inputs=extra_inputs,
    )

    # finalize provider contexts based on collected inputs
    finalize_provider_contexts(
        module_cache,
        instances,
        received_inputs,
        provider_contexts,
        all_providers_list,
        global_context=global_context,
    )

    # re-apply global overrides after finalization
    if context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            context_overrides,
        )

    # and likewise re-apply per-provider overrides so the contexts exposed
    # in the returned `SessionBundle` object include any project-supplied values.
    _apply_provider_overrides(provider_contexts, provider_overrides)

    collect_provider_contributions(module_cache, provider_contexts, accum)

    return SessionBundle(
        anchors=accum.merged_anchors,
        delete_files=list(accum.delete_set),
        file_mappings=accum.merged_file_mappings,
        create_only_files=list(accum.create_only_set),
        delete_history=accum.history,
        provider_contexts=provider_contexts,
        suppressed_sources=accum.suppressed_sources,
        promoted_file_mappings=accum.promoted_file_mappings,
    )


@overload
def create_providers(
    directories: list[str | tuple[str, str]],
    context_overrides: dict[str, object] | None = ...,
    *,
    provider_overrides: dict[str, dict[str, object]] | None = ...,
    global_context: GlobalContext | None = ...,
    extra_provider_entries: list[ProviderEntry] | None = ...,
    extra_inputs: list[BaseInputs] | None = ...,
    dry_run: Literal[False] = ...,
) -> SessionBundle: ...


@overload
def create_providers(
    directories: list[str | tuple[str, str]],
    context_overrides: dict[str, object] | None = ...,
    *,
    provider_overrides: dict[str, dict[str, object]] | None = ...,
    global_context: GlobalContext | None = ...,
    extra_provider_entries: list[ProviderEntry] | None = ...,
    extra_inputs: list[BaseInputs] | None = ...,
    dry_run: Literal[True],
) -> DryRunResult: ...


def create_providers(  # noqa: PLR0913
    directories: list[str | tuple[str, str]],
    context_overrides: dict[str, object] | None = None,
    *,
    provider_overrides: dict[str, dict[str, object]] | None = None,
    global_context: GlobalContext | None = None,
    extra_provider_entries: list[ProviderEntry] | None = None,
    extra_inputs: list[BaseInputs] | None = None,
    dry_run: bool = False,
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

    module_cache = _load_module_cache(normalized_dirs)
    # provider contexts are populated by _populate_provider_context via
    # create_context(); start empty so the guard in
    # _synthesize_provider_context_for_pid correctly calls create_context()
    # for every provider (a pre-seeded BaseContext() instance would satisfy
    # the isinstance guard and cause create_context() to be skipped).
    provider_contexts: dict[str, BaseContext] = {}

    return _run_provider_pipeline(
        module_cache,
        provider_contexts,
        PipelineOptions(
            global_context=global_ctx_obj,
            context_overrides=context_overrides,
            provider_overrides=provider_overrides,
            alias_map=alias_map,
            dry_run=dry_run,
            extra_provider_entries=extra_provider_entries,
            extra_inputs=extra_inputs,
        ),
    )
