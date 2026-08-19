from __future__ import annotations

import inspect
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from repolish.insertions.models import BlockContext, InsertionBlock
from repolish.providers._log import logger
from repolish.providers.models import (
    Accumulators,
    Action,
    BaseContext,
    Decision,
    FileMappingOptions,
    FileMode,
    FileValidatorEntry,
    FileValidatorOptions,
    FileValidatorSpec,
    InsertionRegistry,
    ProviderContributions,
    TemplateMapping,
    call_provider_method,
)
from repolish.providers.models import (
    Provider as _ProviderBase,
)
from repolish.providers.models.template_path import RepolishTemplatePath

if TYPE_CHECKING:
    from collections.abc import Callable

    from repolish.config.models.provider import ProviderOverrides


def _build_insertion_attempts(
    *,
    params: tuple[inspect.Parameter, ...],
    base_kwargs: dict[str, object],
    block: InsertionBlock,
    own_ctx: BaseContext,
) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    """Return invocation attempts in order of preference for an insertion renderer."""
    allowed = {p.name for p in params}
    keyword_args = _build_keyword_args(
        base_kwargs,
        allowed,
        params,
        block,
        own_ctx,
    )

    attempts: list[tuple[tuple[object, ...], dict[str, object]]] = []
    # Prefer the natural call form: marker args as positional args plus injected
    # typed context kwargs, as long as this doesn't double-bind positional names.
    if not _has_positional_keyword_conflict(
        params,
        keyword_args,
        len(block.args),
    ):
        attempts.append((tuple(block.args), keyword_args))
    attempts.append(((), keyword_args))
    attempts.append((tuple(block.args), {}))
    attempts.append(((), {}))
    return attempts


def _has_positional_keyword_conflict(
    params: tuple[inspect.Parameter, ...],
    kwargs: dict[str, object],
    positional_count: int,
) -> bool:
    """Return True when positional args would collide with provided kwargs."""
    if not kwargs or positional_count <= 0:
        return False

    positional_or_keyword_names = [p.name for p in params if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
    consumed = set(positional_or_keyword_names[:positional_count])
    return bool(consumed.intersection(kwargs))


def _build_keyword_args(
    base_kwargs: dict[str, object],
    allowed: set[str],
    params: tuple[inspect.Parameter, ...],
    block: InsertionBlock,
    own_ctx: BaseContext,
) -> dict[str, object]:
    """Build keyword args, injecting BlockContext/InsertionBlock if requested."""
    has_var_keywords = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    if has_var_keywords:
        return base_kwargs

    keyword_args = {k: v for k, v in base_kwargs.items() if k in allowed}
    _inject_context_if_requested(keyword_args, params, block, own_ctx)
    return keyword_args


def _inject_context_if_requested(
    keyword_args: dict[str, object],
    params: tuple[inspect.Parameter, ...],
    block: InsertionBlock,
    own_ctx: BaseContext,
) -> None:
    """Inject BlockContext/InsertionBlock into keyword args when requested by annotation."""
    for p in params:
        if p.kind is not inspect.Parameter.KEYWORD_ONLY:
            continue
        if _is_block_context_annotation(p.annotation):
            keyword_args[p.name] = BlockContext(
                tag=block.tag,
                args=block.args,
                repolish=own_ctx.repolish,
                provider_context=None,
            )
        elif _is_insertion_block_annotation(p.annotation):
            keyword_args[p.name] = block


def _is_block_context_annotation(annotation: object) -> bool:
    """Check if an annotation refers to BlockContext."""
    if annotation is BlockContext:
        return True
    return bool(isinstance(annotation, str) and annotation == 'BlockContext')


def _is_insertion_block_annotation(annotation: object) -> bool:
    """Check if an annotation refers to InsertionBlock."""
    if annotation is InsertionBlock:
        return True
    if isinstance(annotation, str):
        return annotation == 'InsertionBlock' or annotation.endswith(
            '.InsertionBlock',
        )
    forward_arg = getattr(annotation, '__forward_arg__', None)
    if isinstance(forward_arg, str):
        return forward_arg == 'InsertionBlock' or forward_arg.endswith(
            '.InsertionBlock',
        )
    return False


def _insertion_fn_name(fn: Callable[..., str]) -> str:
    """Return a display-friendly insertion function name."""
    return cast('str', fn.__name__) if hasattr(fn, '__name__') else repr(fn)


def _ensure_supported_insertion_signature(
    fn_name: str,
    *,
    has_varargs: bool,
    has_typed_injected_context: bool,
) -> None:
    """Fail fast for unsupported insertion signatures."""
    if has_varargs and has_typed_injected_context:
        msg = (
            f'Insertion function {fn_name!r} cannot combine *args with '
            'BlockContext/InsertionBlock annotations. Use explicit positional '
            'arguments and keyword-only annotated context parameters.'
        )
        raise TypeError(msg)


def _invoke_insertion_attempt(
    fn: Callable[..., str],
    sig: inspect.Signature,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> str | None:
    """Invoke one signature-checked insertion attempt."""
    try:
        sig.bind(*args, **kwargs)
    except TypeError:
        return None
    return fn(*args, **kwargs)


def _render_from_attempts(
    fn: Callable[..., str],
    sig: inspect.Signature,
    attempts: list[tuple[tuple[object, ...], dict[str, object]]],
    *,
    fn_name: str,
) -> str:
    """Return the first successful rendering from attempted call patterns."""
    for args, kwargs in attempts:
        rendered = _invoke_insertion_attempt(fn, sig, args, kwargs)
        if rendered is not None:
            return rendered

    msg = f'Cannot call insertion function {fn_name!r} with supported arguments.'
    raise TypeError(msg)


def _build_insertion_wrapper(
    fn: Callable[..., str],
    own_ctx: BaseContext,
) -> Callable[[InsertionBlock], str]:
    """Adapt provider insertion functions to the writer's block renderer contract."""
    sig = inspect.signature(fn)
    params = tuple(sig.parameters.values())
    fn_name = _insertion_fn_name(fn)
    has_varargs = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params)
    has_typed_injected_context = any(
        _is_block_context_annotation(p.annotation) or _is_insertion_block_annotation(p.annotation) for p in params
    )

    def _render(block: InsertionBlock) -> str:
        _ensure_supported_insertion_signature(
            fn_name,
            has_varargs=has_varargs,
            has_typed_injected_context=has_typed_injected_context,
        )

        base_kwargs: dict[str, object] = {
            'context': own_ctx,
            'block': block,
            'tag': block.tag,
            'function': block.function,
            'args': block.args,
            'body': block.body,
            'comment_style': block.comment_style,
        }

        attempts = _build_insertion_attempts(
            params=params,
            base_kwargs=base_kwargs,
            block=block,
            own_ctx=own_ctx,
        )
        return _render_from_attempts(fn, sig, attempts, fn_name=fn_name)

    return _render


def _bind_insertions_with_context(
    insertions: InsertionRegistry,
    own_ctx: BaseContext,
) -> InsertionRegistry:
    """Return insertion functions wrapped with the provider's own context."""
    bound: InsertionRegistry = {}
    for function_name, fn in insertions.items():
        bound[function_name] = _build_insertion_wrapper(fn, own_ctx)
    return bound


def _apply_annotated_tm(
    dest: str,
    annotated: TemplateMapping,
    provider_id: str,
    accum: Accumulators,
) -> None:
    """Apply a fully-annotated TemplateMapping to the accumulators."""
    path = Path(*PurePosixPath(dest).parts)
    key = path.as_posix()
    if annotated.file_mode == FileMode.DELETE:
        accum.delete_set.add(path)
        accum.merged_file_mappings.pop(dest, None)
        accum.history.setdefault(key, []).append(
            Decision(source=provider_id, action=Action.delete),
        )
    elif annotated.file_mode == FileMode.KEEP:
        accum.delete_set.discard(path)
        accum.history.setdefault(key, []).append(
            Decision(source=provider_id, action=Action.keep),
        )
    elif annotated.file_mode == FileMode.SUPPRESS:
        # Don't render or stage this file; record the source template path so
        # the renderer can skip it even if it was staged by another provider.
        if annotated.source_template:
            accum.suppressed_sources.add(annotated.source_template)
        accum.merged_file_mappings.pop(dest, None)
    else:
        if annotated.file_mode == FileMode.CREATE_ONLY:
            accum.create_only_set.add(path)
        accum.merged_file_mappings[dest] = annotated


def _effective_enabled_state(
    dest: str,
    annotated: str | TemplateMapping,
    config_overrides: dict[str, FileMappingOptions] | None = None,
) -> bool:
    """Determine the effective enabled state for a file mapping.

    Config overrides take precedence over provider-declared options.
    """
    config_opts = config_overrides.get(dest) if config_overrides else None
    if config_opts is not None:
        return config_opts.enabled
    if isinstance(annotated, TemplateMapping) and annotated.options is not None:
        return annotated.options.enabled
    return True


def _process_provider_fm(
    provider_id: str,
    fm: dict[str, str | TemplateMapping | None],
    accum: Accumulators,
    config_overrides: dict[str, FileMappingOptions] | None = None,
) -> None:
    """Process one provider's file_mappings in a single pass.

    Handles all modes in order: plain string sources, DELETE, KEEP,
    CREATE_ONLY, and REGULAR entries.  Populates `merged_file_mappings`,
    `delete_set`, `create_only_set`, and `history` on `accum`.

    Config overrides (from ``ProviderContributions``) take precedence over the
    provider's own ``TemplateMapping.options``.
    """
    for dest, src in fm.items():
        if src is None:
            # the provider explicitly opted out of this template path; record
            # it so the builder can exclude it from auto-staging.
            accum.suppressed_sources.add(dest)
            continue

        effective_enabled = _effective_enabled_state(
            dest,
            src,
            config_overrides,
        )

        if not effective_enabled:
            accum.disabled_file_mappings[dest] = provider_id
            accum.suppressed_sources.add(dest)
            continue

        if isinstance(src, str):
            # Wrap plain-string sources in a TemplateMapping so they carry
            # source_provider. Store with .jinja stripped to match what's
            # on disk after staging.
            tpl = RepolishTemplatePath.from_string(src)
            accum.merged_file_mappings[dest] = TemplateMapping(
                source_template=tpl.logical_name,
                source_provider=provider_id,
            )
            continue
        # For existing TemplateMapping, strip .jinja from source_template
        # to match what will be on disk after staging
        tpl = RepolishTemplatePath.from_string(src.source_template) if src.source_template else None
        annotated = TemplateMapping(
            source_template=tpl.logical_name if tpl else None,
            extra_context=src.extra_context,
            file_mode=src.file_mode,
            options=src.options,
            source_provider=provider_id,
        )
        _apply_annotated_tm(dest, annotated, provider_id, accum)


def _collect_promoted_fm(
    provider_id: str,
    pfm: dict[str, str | TemplateMapping | None],
    accum: Accumulators,
) -> None:
    """Fold a provider's promote_file_mappings dict into ``accum.promoted_file_mappings``."""
    for dest, src in pfm.items():
        if src is None:
            continue
        if isinstance(src, str):
            # Strip .jinja to match what will be on disk after staging
            tpl = RepolishTemplatePath.from_string(src)
            accum.promoted_file_mappings[dest] = TemplateMapping(
                source_template=tpl.logical_name,
                source_provider=provider_id,
            )
        else:
            # Strip .jinja from source_template to match staged file
            tpl = RepolishTemplatePath.from_string(src.source_template) if src.source_template else None
            accum.promoted_file_mappings[dest] = TemplateMapping(
                source_template=tpl.logical_name if tpl else None,
                extra_context=src.extra_context,
                file_mode=src.file_mode,
                promote_conflict=src.promote_conflict,
                source_provider=provider_id,
            )


def _handle_promote_file_mappings(
    inst: _ProviderBase,
    own_ctx: BaseContext,
    provider_id: str,
    accum: Accumulators,
) -> None:
    """Call promote_file_mappings and route the result based on workspace mode."""
    workspace_mode = own_ctx.repolish.workspace.mode
    pfm = cast(
        'dict[str, str | TemplateMapping | None]',
        call_provider_method(inst, 'promote_file_mappings', own_ctx),
    )
    if workspace_mode == 'member':
        if pfm:
            _collect_promoted_fm(provider_id, pfm, accum)
    elif pfm:
        logger.warning(
            'promote_file_mappings_ignored_in_non_member_mode',
            provider=provider_id,
            mode=workspace_mode,
            suggestion='promote_file_mappings is only effective in member mode',
        )


def _get_inst_and_ctx(
    provider_id: str,
    module_dict: dict,
    provider_contexts: dict[str, BaseContext],
) -> tuple[_ProviderBase, BaseContext] | None:
    """Return the provider instance and its context for a given provider_id."""
    inst = module_dict.get('_repolish_provider_instance')
    if not inst:
        return None
    inst = cast('_ProviderBase', inst)
    own_ctx = provider_contexts.get(provider_id, BaseContext())
    if not isinstance(own_ctx, BaseContext):
        return None
    return inst, own_ctx


def _suppress_auto_staged_files(
    provider_id: str,
    fm_config_opts: dict[str, FileMappingOptions] | None,
    accum: Accumulators,
) -> None:
    """Suppress auto-staged files disabled via config overrides.

    Explicitly-mapped files are already handled inside _process_provider_fm.
    """
    if fm_config_opts:
        for dest, opts in fm_config_opts.items():
            if not opts.enabled:
                accum.merged_file_mappings.pop(dest, None)
                accum.disabled_file_mappings.setdefault(dest, provider_id)
                accum.suppressed_sources.add(dest)


def _handle_provider_file_mappings(
    inst: _ProviderBase,
    own_ctx: BaseContext,
    provider_id: str,
    accum: Accumulators,
    provider_overrides: ProviderOverrides | None,
) -> None:
    """Collect and normalize file_mappings contributions for one provider."""
    fm = cast(
        'dict[str, str | TemplateMapping | None]',
        call_provider_method(inst, 'create_file_mappings', own_ctx),
    )
    fm_config_opts = provider_overrides.file_mappings if provider_overrides else None
    _process_provider_fm(
        provider_id,
        fm,
        accum,
        config_overrides=fm_config_opts,
    )
    _suppress_auto_staged_files(provider_id, fm_config_opts, accum)


def _handle_provider_validators(
    inst: _ProviderBase,
    own_ctx: BaseContext,
    provider_id: str,
    accum: Accumulators,
) -> None:
    """Collect validator registrations for one provider.

    The validator registry is additive, but the per-file source ownership used for
    summary/display and override targeting should follow the most recently
    contributed provider for that file path. This keeps the human-facing "who
    owns this validator" metadata aligned with the provider that actually
    declared the check for the target path.
    """
    validators = cast(
        'dict[str, dict[str, FileValidatorEntry]]',
        call_provider_method(inst, 'create_file_validators', own_ctx),
    )
    for path, path_validators in validators.items():
        accum.file_validators.setdefault(path, {}).update(path_validators)
        accum.validator_sources[path] = provider_id


def _handle_provider_insertions(
    inst: _ProviderBase,
    own_ctx: BaseContext,
    provider_id: str,
    accum: Accumulators,
) -> None:
    """Collect insertion-function registrations for one provider.

    This mirrors validation registration but keeps the registry keyed by file path
    and function name so later resolution can look up the callables by the parsed
    insertion metadata without leaking registration state across monorepo modes.
    """
    insertions = cast(
        'dict[str, InsertionRegistry]',
        call_provider_method(inst, 'create_file_insertions', own_ctx),
    )
    provider_name = inst.alias or provider_id
    for path, functions in insertions.items():
        registry = accum.file_insertions.setdefault(path, {})
        for function_name, bound_fn in _bind_insertions_with_context(
            functions,
            own_ctx,
        ).items():
            # Keep the first unqualified name as deterministic fallback.
            registry.setdefault(function_name, bound_fn)
            # Always expose provider-qualified keys for explicit targeting.
            registry[f'{provider_name}:{function_name}'] = bound_fn
        accum.insertion_sources.setdefault(path, []).append(provider_id)


def _override_validator_entry(
    entry: FileValidatorEntry,
    *,
    enabled: bool,
) -> FileValidatorEntry:
    """Return a validator entry with the requested enabled state."""
    if callable(entry):
        if enabled:
            return entry
        return FileValidatorSpec(
            fn=entry,
            options=FileValidatorOptions(enabled=False),
        )
    # entry is a FileValidatorSpec; return a new spec with the updated enabled state
    updated = entry.options.model_copy(update={'enabled': enabled})
    return FileValidatorSpec(
        fn=entry.fn,
        options=updated,
    )


def _disable_validators_for_file(
    validators: dict[str, FileValidatorEntry],
    validator_overrides: dict[str, bool],
) -> None:
    """Apply config-based validator flags to a single file's validator registry."""
    for name, enabled in validator_overrides.items():
        entry = validators.get(name)
        if entry is not None:
            validators[name] = _override_validator_entry(entry, enabled=enabled)


def _apply_validator_overrides(
    overrides: ProviderOverrides | None,
    accum: Accumulators,
) -> None:
    """Disable any validators explicitly turned off by config overrides."""
    if not overrides or not overrides.validators:
        return
    for dest, validator_overrides in overrides.validators.items():
        validators = accum.file_validators.get(dest)
        if validators is None or not validator_overrides:
            continue
        _disable_validators_for_file(validators, validator_overrides)
        if not validators:
            accum.file_validators.pop(dest, None)


def _collect_provider_contribution(
    provider_id: str,
    module_dict: dict,
    provider_contexts: dict[str, BaseContext],
    accum: Accumulators,
    contributions: ProviderContributions | None = None,
) -> None:
    """Process a single provider's anchors, file mappings, and promotions."""
    inst_ctx = _get_inst_and_ctx(provider_id, module_dict, provider_contexts)
    if not inst_ctx:
        return
    inst, own_ctx = inst_ctx

    # Look up this provider's overrides from contributions once.
    provider_overrides: ProviderOverrides | None = contributions.overrides.get(provider_id) if contributions else None

    val = call_provider_method(inst, 'create_anchors', own_ctx)
    if not isinstance(val, dict):
        msg = 'create_anchors() must return a dict'
        raise TypeError(msg)
    accum.merged_anchors.update(cast('dict[str, str]', val))
    if provider_overrides and provider_overrides.anchors:
        accum.merged_anchors.update(provider_overrides.anchors)

    _handle_provider_file_mappings(
        inst,
        own_ctx,
        provider_id,
        accum,
        provider_overrides,
    )
    _handle_provider_validators(inst, own_ctx, provider_id, accum)
    _handle_provider_insertions(inst, own_ctx, provider_id, accum)
    _apply_validator_overrides(provider_overrides, accum)
    _handle_promote_file_mappings(inst, own_ctx, provider_id, accum)


def collect_provider_contributions(
    module_cache: list[tuple[str, dict]],
    provider_contexts: dict[str, BaseContext],
    accum: Accumulators,
    contributions: ProviderContributions | None = None,
) -> None:
    """Collect anchors, file mappings, and delete/create-only decisions from all providers.

    This mutates the provided accumulators in-place.
    """
    for provider_id, module_dict in module_cache:
        _collect_provider_contribution(
            provider_id,
            module_dict,
            provider_contexts,
            accum,
            contributions=contributions,
        )
