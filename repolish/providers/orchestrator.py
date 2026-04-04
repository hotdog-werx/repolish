from collections.abc import Sequence
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
    _opts = options or PipelineOptions()

    instances = build_provider_metadata(module_cache)
    _set_provider_metadata(module_cache, instances, _opts.alias_map or {})

    _populate_provider_context(
        module_cache,
        instances,
        provider_contexts,
        _opts.global_context,
    )
    _apply_provider_overrides(provider_contexts, _opts.provider_overrides)

    all_providers_list: list[ProviderEntry] = _build_all_providers_list(
        module_cache,
        instances,
        provider_contexts,
        alias_map=_opts.alias_map,
    )

    if _opts.extra_provider_entries:
        all_providers_list = all_providers_list + _opts.extra_provider_entries

    if _opts.context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            _opts.context_overrides,
        )

    if _opts.dry_run:
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

    received_inputs = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        extra_inputs=_opts.extra_inputs,
    )

    finalize_provider_contexts(
        module_cache,
        instances,
        received_inputs,
        provider_contexts,
        all_providers_list,
        global_context=_opts.global_context,
    )

    if _opts.context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            _opts.context_overrides,
        )
    _apply_provider_overrides(provider_contexts, _opts.provider_overrides)

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
    directories: Sequence[str | tuple[str, str]],
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
    directories: Sequence[str | tuple[str, str]],
    context_overrides: dict[str, object] | None = ...,
    *,
    provider_overrides: dict[str, dict[str, object]] | None = ...,
    global_context: GlobalContext | None = ...,
    extra_provider_entries: list[ProviderEntry] | None = ...,
    extra_inputs: list[BaseInputs] | None = ...,
    dry_run: Literal[True],
) -> DryRunResult: ...


def create_providers(  # noqa: PLR0913
    directories: Sequence[str | tuple[str, str]],
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
