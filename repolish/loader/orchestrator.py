import copy
from dataclasses import dataclass, field
from inspect import isclass
from pathlib import Path
from typing import Any, cast

from repolish.loader import (
    Accumulators,
    Decision,
    ProviderEntry,
    Providers,
    TemplateMapping,
)
from repolish.loader import Provider as _ProviderBase
from repolish.loader._log import logger
from repolish.loader.anchors import process_anchors
from repolish.loader.context import (
    apply_context_overrides,
)
from repolish.loader.create_only import process_create_only_files
from repolish.loader.deletes import process_delete_files
from repolish.loader.mappings import process_file_mappings
from repolish.loader.models import (
    BaseContext,
    GlobalContext,
    get_global_context,
)
from repolish.loader.module import get_module
from repolish.loader.three_phase import (
    build_provider_metadata,
    compute_recipient_flags,
    finalize_provider_contexts,
    gather_received_inputs,
)


def _find_provider_class(
    module_dict: dict[str, object],
) -> type[_ProviderBase] | None:
    """Return the single Provider subclass exported in `module_dict`.

    If the module exports no subclasses `None` is returned.  The loader
    historically picked the *first* subclass it encountered, but this hid
    user errors where a file accidentally defined multiple providers (e.g.
    importing another provider class into the same module).  The caller
    (`_maybe_instantiate_provider`) expects at most one class; if there are
    multiple we raise a `RuntimeError` so the problem is detected right
    away.

    Keeping the detection logic isolated makes the behaviour easy to test
    and keeps the surrounding code simple.
    """
    providers: list[type[_ProviderBase]] = [
        val
        for val in module_dict.values()
        if isclass(val) and issubclass(val, _ProviderBase) and val is not _ProviderBase
    ]

    # If the module defines ``__all__`` we treat it as the explicit export
    # list.  this lets authors import other provider classes for utility
    # purposes while still exporting a single implementation.  the list may
    # contain arbitrary names; we only consider entries that match provider
    # class names.  if a single provider appears in ``__all__`` we return
    # that class even if others are present at module level.  the module may
    # still define no public providers, in which case we behave as though
    # no subclass were exported.
    all_list = module_dict.get('__all__')
    if isinstance(all_list, (list, tuple)) and all_list:
        # filter the providers down to those listed explicitly
        filtered = [cls for cls in providers if cls.__name__ in all_list]
        if len(filtered) == 1:
            return filtered[0]
        if len(filtered) > 1:
            names = ', '.join(cls.__name__ for cls in filtered)
            msg = f'__all__ exports multiple Provider subclasses ({names}); only one class may be exported per file'
            raise RuntimeError(msg)
        # if ``__all__`` is present but doesn't mention any providers we
        # continue with the normal logic below; the user has effectively
        # hidden all classes from export.

    if not providers:
        return None
    if len(providers) > 1:
        names = ', '.join(cls.__name__ for cls in providers)
        msg = (
            f'provider module exports multiple Provider subclasses ({names}); '
            'only one class may be defined per file; if you meant to expose a '
            'single implementation please add that class name to ``__all__``'
        )
        raise RuntimeError(msg)
    return providers[0]


def _maybe_instantiate_provider(
    module_dict: dict[str, object],
) -> None:
    """Instantiate a Provider subclass and store the instance in `module_dict`.

    The instance is stored under ``_repolish_provider_instance`` for later
    retrieval by ``_process_phase_two`` and diagnostics.  Raises
    ``RuntimeError`` if the module does not export exactly one subclass.
    """
    cls = _find_provider_class(module_dict)
    if not cls:
        msg = 'provider module does not export a Provider subclass'
        raise RuntimeError(msg)

    module_dict['_repolish_provider_instance'] = cls()


def _load_module_cache(directories: list[str]) -> list[tuple[str, dict]]:
    """Load provider modules and validate them.

    Returns a list of (provider_id, module_dict) tuples.
    """
    cache: list[tuple[str, dict]] = []
    for directory in directories:
        module_path = Path(directory) / 'repolish.py'
        module_dict = get_module(str(module_path))
        provider_id = Path(directory).as_posix()

        # Detect and instantiate class-based providers
        _maybe_instantiate_provider(module_dict)

        cache.append((provider_id, module_dict))
    return cache


def _process_phase_two(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    accum: Accumulators,
) -> None:
    """Phase 2: process anchors, file mappings, delete/create-only files.

    This mutates the provided accumulators in-place.
    """
    for provider_id, module_dict in module_cache:
        # module_dict always has a provider instance injected by _load_module_cache
        inst = module_dict.get('_repolish_provider_instance')
        if not inst:
            # should not happen, but skip defensively
            continue
        inst = cast('_ProviderBase', inst)

        own_ctx = provider_contexts.get(provider_id, {})
        process_anchors(inst, own_ctx, accum.merged_anchors)
        # compute file mappings once per provider and forward the result to the
        # helpers.  this avoids three separate calls to
        # `inst.create_file_mappings()` and decouples the helpers from the
        # provider API (making future adapter removal easier).
        fm = inst.create_file_mappings(own_ctx)
        process_file_mappings(provider_id, fm, accum)
        process_delete_files(fm, accum.delete_set, provider_id, accum.history)
        process_create_only_files(fm, accum.create_only_set)


def _build_all_providers_list(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, BaseContext],
    *,
    alias_map: dict[str, str] | None = None,
) -> list[ProviderEntry]:
    """Return the `all_providers_list` used for input routing.

    Pulling this logic into a helper reduces the complexity of the
    surrounding function and keeps the iteration simple to read.
    """
    all_providers_list: list[ProviderEntry] = []
    for idx, (pid, _mod) in enumerate(module_cache):
        schema = None
        inst = instances[idx]
        name: str | None = None
        alias: str | None = None
        inst_type: type[Any] | None = None
        ctx_obj = provider_contexts.get(pid)
        ctx_type: type[BaseContext] | None = None

        if inst is not None:
            try:
                schema = inst.get_inputs_schema()
            except Exception:  # noqa: BLE001 - don't let one provider's broken schema prevent the whole run
                # DO LATER: consider logging this error so providers can diagnose their broken schema
                schema = None
            # `name` is the provider's own name; `alias` is the
            # configuration key (here we mirror provider_id since that's what
            # create_providers passes).
            try:
                name = inst.get_provider_name()
            except Exception:  # noqa: BLE001 - avoid failing the build on a broken provider
                name = None
            alias = pid
            inst_type = type(inst)

        # if context object is a BaseModel we remember its class
        if isinstance(ctx_obj, BaseContext):
            ctx_type = type(ctx_obj)

        # if an alias map was provided, prefer it over the default
        # value we computed earlier.
        if alias_map is not None and pid in alias_map:
            alias = alias_map[pid]

        all_providers_list.append(
            ProviderEntry(
                provider_id=pid,
                name=name,
                alias=alias,
                inst_type=inst_type,
                context=ctx_obj or BaseContext(),
                context_type=ctx_type,
                input_type=schema,
            ),
        )
    return all_providers_list


# helper used by both override-appliers.  extracted to reduce duplication and
# make the higher-level loops easier to understand.
def _apply_overrides_to_model(
    ctx: BaseContext,
    overrides: dict[str, object],
    provider: str | None = None,
) -> BaseContext:
    """Return a new `BaseModel` with `overrides` applied, or the original.

    The implementation mirrors the complexity that formerly lived inline in the
    two callers.  We dump the model to a dictionary, deep-copy it (to avoid
    shared-mutable data issues), mutate the copy via
    :func:`apply_context_overrides` and then re-validate the result.  If
    validation raises or silently discards keys the user supplied we log a
    warning including the provider identifier when available.  The original
    model instance is returned on failure so the caller need not handle
    fallback logic.

    `provider` is used only for logging context; callers may pass `None`.
    """
    original = ctx.model_dump()
    data = copy.deepcopy(original)
    apply_context_overrides(data, overrides)
    if data == original:
        return ctx

    try:
        new_ctx = ctx.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            'context_override_validation_failed',
            provider=provider,
            error=str(exc),
        )
        return ctx
    new_data = new_ctx.model_dump()
    if new_data != data:
        dropped = {k for k in data if k not in new_data}
        if dropped:
            # only warn when actual keys were removed; modifications of
            # existing values (including those performed by validators) are
            # expected and should not emit a misleading warning.
            logger.warning(
                'context_override_ignored',
                provider=provider,
                ignored_keys=sorted(dropped),
            )
    return new_ctx


def _apply_overrides_to_provider_contexts(
    provider_contexts: dict[str, BaseContext],
    context_overrides: dict[str, object],
) -> None:
    """Apply configuration overrides to each provider's context.

    This handles both `BaseModel` and `dict` contexts and is used
    both before inputs are gathered and after finalization so that the
    authoritative overrides cannot be bypassed by provider logic.

    When operating on a `BaseModel` we convert to raw data, apply the
    overrides and then re-validate back into the same model class.  Prior to
    <2026-02> we would fall back to the raw data on validation failure,
    inadvertently turning the context into a plain `dict`.  Because
    `provide_inputs`/`finalize_context` are only invoked with model
    instances this could lead to mysterious `AttributeError` crashes.  We
    now catch validation errors, log a warning, and retain the original
    model instance instead.  The warning makes it clear when user-supplied
    overrides could not be applied (for example, the override targets a
    field that doesn't exist yet or violates the model schema).
    """
    for pid, ctx in provider_contexts.items():
        provider_contexts[pid] = _apply_overrides_to_model(
            ctx,
            context_overrides,
            provider=pid,
        )


def _apply_provider_overrides(
    provider_contexts: dict[str, BaseContext],
    provider_overrides: dict[str, dict[str, object]] | None,
) -> None:
    """Apply per-provider overrides (handles BaseModel and dict contexts).

    Extracted helper to reduce duplication in the three-phase workflow.
    Behaviour mirrors :func:`_apply_overrides_to_provider_contexts` --
    failures are logged and the original context is preserved.
    """
    if not provider_overrides:
        return

    for pid, overrides in provider_overrides.items():
        ctx = provider_contexts.get(pid)
        if ctx:
            provider_contexts[pid] = _apply_overrides_to_model(
                ctx,
                overrides,
                provider=pid,
            )


@dataclass(frozen=True)
class RunThreePhaseContext:
    """Typed container for optional runtime parameters used by the three-phase provider runner."""

    context_overrides: dict[str, object] | None = None
    provider_overrides: dict[str, dict[str, object]] | None = None
    alias_map: dict[str, str] | None = None  # provider_id -> config alias
    global_context: GlobalContext = field(default_factory=GlobalContext)


def _synthesize_provider_context_for_pid(
    inst: _ProviderBase,
    pid: str,
    provider_contexts: dict[str, BaseContext],
    global_context: GlobalContext,
) -> None:
    """Ensure `provider_contexts[pid]` contains a typed context for class-based providers.

    Call `create_context`, fall back to existing value on error, and
    inject the shared `GlobalContext` into provider contexts that declare
    a `repolish` field (i.e. subclasses of `BaseContext`).
    """
    if isinstance(provider_contexts.get(pid), BaseContext):
        return

    try:
        # create_context is generic but its bound by BaseContext
        ctx = cast('BaseContext', inst.create_context())
    except Exception:  # noqa: BLE001 - don't let one provider stop the run
        return

    if isinstance(ctx, BaseContext) and hasattr(ctx, 'repolish'):
        ctx = ctx.model_copy(update={'repolish': global_context})

    provider_contexts[pid] = ctx


def _populate_provider_context(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    provider_contexts: dict[str, BaseContext],
    global_context: GlobalContext,
) -> None:
    """Populate `provider_contexts` with typed context objects for each provider.

    Must run before schemas are inspected or overrides applied so that
    `provide_inputs` receives a typed context object rather than an empty
    placeholder.
    """
    for idx, (pid, _mod) in enumerate(module_cache):
        inst = instances[idx]
        if inst is None:  # pragma: no cover - load path always provides instances
            continue
        _synthesize_provider_context_for_pid(
            inst,
            pid,
            provider_contexts,
            global_context,
        )


def _run_three_phase(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    options: RunThreePhaseContext | None = None,
) -> Providers:
    """Execute phase-2/3 logic and return final Providers object.

    The original implementation accepted multiple separate arguments and had
    accumulated complexity.  Bundling optional parameters into `options`
    and extracting helpers reduces the function's signature and cognitive
    complexity while preserving behaviour.
    """
    # initialize accumulators that were previously defined at the top of
    # `create_providers`.
    merged_anchors: dict[str, str] = {}
    merged_file_mappings: dict[str, str | TemplateMapping] = {}
    create_only_set: set[Path] = set()
    delete_set: set[Path] = set()
    history: dict[str, list[Decision]] = {}

    # gather metadata and basic helper structures
    instances = build_provider_metadata(module_cache)

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

    # apply overrides before input gathering
    if context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            context_overrides,
        )

    # we no longer attempt to predict receivers; just call all providers
    # for their outgoing inputs and route them based on schemas.
    received_inputs = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        # old flag still passed for compatibility but ignored
        compute_recipient_flags(instances),
    )

    # finalize provider contexts based on collected inputs
    finalize_provider_contexts(
        module_cache,
        instances,
        received_inputs,
        provider_contexts,
        all_providers_list,
    )

    # re-apply global overrides after finalization
    if context_overrides:
        _apply_overrides_to_provider_contexts(
            provider_contexts,
            context_overrides,
        )

    # and likewise re-apply per-provider overrides so the contexts exposed
    # in the returned `Providers` object include any project-supplied values.
    _apply_provider_overrides(provider_contexts, provider_overrides)

    accum = Accumulators(
        merged_anchors=merged_anchors,
        merged_file_mappings=merged_file_mappings,
        create_only_set=create_only_set,
        delete_set=delete_set,
        history=history,
    )
    _process_phase_two(module_cache, provider_contexts, accum)

    return Providers(
        anchors=accum.merged_anchors,
        delete_files=list(accum.delete_set),
        file_mappings=accum.merged_file_mappings,
        create_only_files=list(accum.create_only_set),
        delete_history=accum.history,
        provider_contexts=provider_contexts,
    )


def create_providers(
    directories: list[str | tuple[str, str]],
    context_overrides: dict[str, object] | None = None,
    *,
    provider_overrides: dict[str, dict[str, object]] | None = None,
) -> Providers:
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
    """
    # Compute the global context once; it is injected into every provider's
    # `repolish` field as a typed object.
    global_ctx_obj = get_global_context()
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

    return _run_three_phase(
        module_cache,
        provider_contexts,
        RunThreePhaseContext(
            global_context=global_ctx_obj,
            context_overrides=context_overrides,
            provider_overrides=provider_overrides,
            alias_map=alias_map,
        ),
    )
