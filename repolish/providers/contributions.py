from __future__ import annotations

import inspect
from pathlib import Path, PurePosixPath
from types import UnionType
from typing import TYPE_CHECKING, Any, Union, cast, get_args, get_origin

from repolish.insertions.models import BlockContext, InsertionBlock
from repolish.insertions.type_utils import (
    is_block_context_annotation,
    is_insertion_block_annotation,
)
from repolish.providers._log import logger
from repolish.providers.models import (
    Accumulators,
    Action,
    BaseContext,
    Decision,
    FileInsertionContribution,
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
from repolish.utils import merge_dicts_first_wins

if TYPE_CHECKING:
    from collections.abc import Callable

    from repolish.config.models.provider import ProviderOverrides


def _build_insertion_attempts(
    *,
    params: tuple[inspect.Parameter, ...],
    block: InsertionBlock,
    own_ctx: BaseContext,
) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    """Return invocation attempts in order of preference for an insertion renderer."""
    keyword_args = _build_typed_injection_kwargs(
        params,
        block,
        own_ctx,
    )
    named_call = _build_named_marker_call(params=params, marker_args=block.args)

    attempts: list[tuple[tuple[object, ...], dict[str, object]]] = []
    if named_call is not None:
        named_positional, named_kwargs = named_call
        merged_named_kwargs = dict(keyword_args)
        merged_named_kwargs.update(named_kwargs)
        attempts.append((named_positional, merged_named_kwargs))
        attempts.append((named_positional, named_kwargs))
        attempts.append(((), merged_named_kwargs))

    attempts.append((tuple(block.args), keyword_args))
    attempts.append(((), keyword_args))
    attempts.append((tuple(block.args), {}))
    attempts.append(((), {}))
    return attempts


def _build_named_marker_call(
    *,
    params: tuple[inspect.Parameter, ...],
    marker_args: tuple[str, ...],
) -> tuple[tuple[object, ...], dict[str, object]] | None:
    """Build a call tuple for key=value marker args, if that style is used."""
    named_values = _parse_named_marker_args(marker_args, params)
    if named_values is None:
        return None

    positional_args: list[object] = []
    keyword_args: dict[str, object] = {}
    marker_params = _marker_value_params(params)
    allowed = {p.name for p in marker_params}

    unknown = sorted(name for name in named_values if name not in allowed)
    if unknown:
        allowed_list = ', '.join(sorted(allowed)) if allowed else '<none>'
        msg = f'Unknown named insertion args: {unknown}. Allowed: {allowed_list}.'
        raise TypeError(msg)

    for param in marker_params:
        value = _marker_value_for_param(param, named_values)
        if param.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }:
            positional_args.append(value)
        else:
            keyword_args[param.name] = value

    return tuple(positional_args), keyword_args


def _parse_named_marker_args(
    marker_args: tuple[str, ...],
    params: tuple[inspect.Parameter, ...],
) -> dict[str, str] | None:
    """Parse key=value marker args using normalized keys, or return None."""
    if not marker_args or not all('=' in arg for arg in marker_args):
        return None

    parsed: dict[str, str] = {}
    for token in marker_args:
        key_raw, value = token.split('=', 1)
        key = key_raw.strip().replace('-', '_')
        if not key:
            msg = f'Invalid named insertion arg {token!r}: key cannot be empty.'
            raise TypeError(msg)
        if key in parsed:
            msg = f'Duplicate named insertion arg {key!r}.'
            raise TypeError(msg)
        parsed[key] = value

    # Avoid breaking existing positional tokens that happen to contain '='.
    marker_param_names = {p.name for p in _marker_value_params(params)}
    if not set(parsed).intersection(marker_param_names):
        return None

    return parsed


def _marker_value_params(
    params: tuple[inspect.Parameter, ...],
) -> list[inspect.Parameter]:
    """Return function params that can consume marker values."""
    result: list[inspect.Parameter] = []
    for param in params:
        if param.kind not in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            continue
        if param.kind is inspect.Parameter.KEYWORD_ONLY and (
            is_block_context_annotation(param.annotation) or is_insertion_block_annotation(param.annotation)
        ):
            continue
        result.append(param)
    return result


def _marker_value_for_param(
    param: inspect.Parameter,
    named_values: dict[str, str],
) -> object:
    """Resolve a marker value for one parameter, allowing omitted None-capable args."""
    if param.name in named_values:
        return named_values[param.name]
    if _parameter_accepts_none(param):
        return None
    msg = (
        f'Missing named insertion arg {param.name!r}. '
        'Omitted named args are only allowed for parameters that accept None.'
    )
    raise TypeError(msg)


def _parameter_accepts_none(param: inspect.Parameter) -> bool:
    """Return True when a parameter can safely receive None."""
    if param.default is None:
        return True
    return _annotation_accepts_none(param.annotation)


def _annotation_accepts_none(annotation: object) -> bool:
    """Return True when an annotation expresses Optional/None compatibility."""
    if annotation in {None, type(None)}:
        return True

    if isinstance(annotation, str):
        compact = annotation.replace(' ', '')
        return compact == 'None' or compact.startswith('Optional[') or '|None' in compact

    origin = get_origin(annotation)
    if origin in {UnionType, Union}:  # `X | None` and `typing.Union`
        return any(arg is type(None) for arg in get_args(annotation))
    return any(arg is type(None) for arg in get_args(annotation))


def _build_typed_injection_kwargs(
    params: tuple[inspect.Parameter, ...],
    block: InsertionBlock,
    own_ctx: BaseContext,
) -> dict[str, object]:
    """Build keyword args for typed context injection only."""
    keyword_args: dict[str, object] = {}
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
        if is_block_context_annotation(p.annotation):
            keyword_args[p.name] = BlockContext(
                tag=block.tag,
                args=block.args,
                repolish=own_ctx.repolish,
                provider_context=None,
                file_path=block.file_path,
                insertion_block=block,
            )
        elif is_insertion_block_annotation(p.annotation):
            keyword_args[p.name] = block


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
        is_block_context_annotation(p.annotation) or is_insertion_block_annotation(p.annotation) for p in params
    )

    def _render(block: InsertionBlock) -> str:
        _ensure_supported_insertion_signature(
            fn_name,
            has_varargs=has_varargs,
            has_typed_injected_context=has_typed_injected_context,
        )

        attempts = _build_insertion_attempts(
            params=params,
            block=block,
            own_ctx=own_ctx,
        )
        return _render_from_attempts(fn, sig, attempts, fn_name=fn_name)

    # Preserve user-facing metadata for diagnostics and list-insertions output.
    cast('Any', _render).__name__ = getattr(fn, '__name__', '_render')
    cast('Any', _render).__doc__ = getattr(fn, '__doc__', None)

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
    provider_overrides: ProviderOverrides | None = None,
) -> None:
    """Collect insertion-function registrations for one provider.

    This mirrors validation registration but keeps the registry keyed by file path
    and function name so later resolution can look up the callables by the parsed
    insertion metadata without leaking registration state across monorepo modes.
    """
    contribution = cast(
        'FileInsertionContribution',
        call_provider_method(inst, 'create_file_insertions', own_ctx),
    )
    shared_registry: InsertionRegistry = {}
    if isinstance(contribution, list):
        shared_registry = cast(
            'InsertionRegistry',
            call_provider_method(inst, 'create_insertion_registry', own_ctx),
        )

    insertions = _normalize_provider_insertions(contribution, shared_registry)
    _extend_provider_insertions(
        insertions,
        extra_paths=(provider_overrides.insertions_extend_files if provider_overrides else None),
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


def _extend_provider_insertions(
    insertions: dict[str, InsertionRegistry],
    *,
    extra_paths: list[str] | None,
) -> None:
    """Extend insertion targets with additional files from config overrides.

    This is intentionally additive: provider-declared file/function mappings
    stay authoritative, while extra paths receive any unqualified function that
    provider already exposes.
    """
    if not extra_paths or not (shared_registry := merge_dicts_first_wins(insertions.values())):
        return

    for path in extra_paths:
        if path:
            # Ensure extra path gets all shared functions, but don't override existing ones
            target = insertions.setdefault(path, {})
            for fn_name, fn in shared_registry.items():
                target.setdefault(fn_name, fn)


def _normalize_provider_insertions(
    contribution: FileInsertionContribution,
    shared_registry: InsertionRegistry | None = None,
) -> dict[str, InsertionRegistry]:
    """Normalize provider insertion contribution into a path->registry map."""
    if isinstance(contribution, dict):
        return contribution
    if isinstance(contribution, list):
        if not all(isinstance(path, str) for path in contribution):
            msg = 'create_file_insertions() list form must contain only destination path strings.'
            raise TypeError(msg)
        registry = shared_registry or {}
        return {path: dict(registry) for path in contribution if path}

    msg = 'create_file_insertions() must return dict[str, InsertionRegistry] or list[str].'
    raise TypeError(msg)


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
    overrides_validators: dict[str, dict[str, bool] | bool],
    accum: Accumulators,
) -> None:
    """Disable any validators explicitly turned off by config overrides."""
    for dest, validator_overrides in overrides_validators.items():
        if (
            isinstance(validator_overrides, dict)
            and validator_overrides
            and (validators := accum.file_validators.get(dest)) is not None
        ):
            _disable_validators_for_file(validators, validator_overrides)
            if not validators:
                accum.file_validators.pop(dest, None)


def _disabled_insertion_renderer_for_function(
    function_name: str,
) -> Callable[[InsertionBlock], str]:
    """Return a disabled renderer tagged with function override metadata."""

    def _render(block: InsertionBlock) -> str:
        return block.body

    cast('Any', _render).__repolish_disabled_functions__ = frozenset(
        {function_name},
    )
    cast('Any', _render).__repolish_disabled_tags__ = frozenset()
    return _render


def _disable_insertions_for_file(
    insertions: InsertionRegistry,
    insertion_overrides: dict[str, bool],
) -> None:
    """Apply config-based insertion enabled flags to a single file registry."""
    if _is_insertion_file_disabled(insertion_overrides):
        insertions.clear()
        return

    for name in _disabled_insertion_names(insertion_overrides):
        _disable_insertion_by_name(insertions, name)

    for tag in _disabled_insertion_tags(insertion_overrides):
        _disable_insertions_by_tag(insertions, tag)


def _is_insertion_file_disabled(insertion_overrides: dict[str, bool]) -> bool:
    """Return True when a file-level insertion disable is configured."""
    return insertion_overrides.get('enabled') is False


def _disabled_insertion_names(
    insertion_overrides: dict[str, bool],
) -> list[str]:
    """Return insertion function names explicitly disabled by config."""
    return [
        name
        for name, enabled in insertion_overrides.items()
        if name != 'enabled' and not _is_insertion_tag_override(name) and not enabled
    ]


def _disabled_insertion_tags(
    insertion_overrides: dict[str, bool],
) -> list[str]:
    """Return insertion block tags explicitly disabled by config."""
    tags: list[str] = []
    for name, enabled in insertion_overrides.items():
        if enabled or not _is_insertion_tag_override(name):
            continue
        tag = name.removeprefix('tag:')
        if tag:
            tags.append(tag)
    return tags


def _is_insertion_tag_override(name: str) -> bool:
    """Return True when an insertion override key targets a block tag."""
    return name.startswith('tag:')


def _disable_insertion_by_name(
    insertions: InsertionRegistry,
    name: str,
) -> None:
    """Disable both unqualified and provider-qualified insertion keys."""
    for key in _matching_insertion_keys(insertions, name):
        insertions[key] = _disabled_insertion_renderer_for_function(name)


def _disable_insertions_by_tag(
    insertions: InsertionRegistry,
    tag: str,
) -> None:
    """Disable insertions only for blocks that match a specific tag."""
    for key, renderer in list(insertions.items()):
        insertions[key] = _wrap_disabled_tag_renderer(renderer, tag)


def _wrap_disabled_tag_renderer(
    renderer: Callable[[InsertionBlock], str],
    disabled_tag: str,
) -> Callable[[InsertionBlock], str]:
    """Wrap a renderer to preserve content for one disabled block tag."""
    inherited_tags = set(
        getattr(renderer, '__repolish_disabled_tags__', frozenset()),
    )
    inherited_tags.add(disabled_tag)
    inherited_functions = frozenset(
        getattr(renderer, '__repolish_disabled_functions__', frozenset()),
    )

    def _render(block: InsertionBlock) -> str:
        return block.body if block.tag == disabled_tag else renderer(block)

    cast('Any', _render).__repolish_disabled_tags__ = frozenset(inherited_tags)
    cast('Any', _render).__repolish_disabled_functions__ = inherited_functions
    return _render


def _matching_insertion_keys(
    insertions: InsertionRegistry,
    name: str,
) -> list[str]:
    """Return registry keys that target an insertion function name."""
    return [key for key in insertions if _matches_insertion_name(key, name)]


def _matches_insertion_name(
    key: str,
    name: str,
) -> bool:
    """Return True when an insertion key matches an override name.

    Accepts either hyphenated or underscored names for convenience.
    """
    if key == name:
        return True

    key_tail = key.rsplit(':', 1)[1] if ':' in key else key
    normalized_key = key_tail.replace('-', '_')
    normalized_name = name.replace('-', '_')
    return normalized_key == normalized_name


def _apply_insertion_overrides(
    overrides_insertions: dict[str, dict[str, bool] | bool],
    accum: Accumulators,
) -> None:
    """Disable insertion functions/files explicitly turned off by config overrides."""
    for dest, insertion_overrides in overrides_insertions.items():
        if (
            isinstance(insertion_overrides, dict)
            and insertion_overrides
            and (insertions := accum.file_insertions.get(dest)) is not None
        ):
            _disable_insertions_for_file(insertions, insertion_overrides)
            if not insertions:
                accum.file_insertions.pop(dest, None)


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
    _handle_provider_insertions(
        inst,
        own_ctx,
        provider_id,
        accum,
        provider_overrides,
    )
    if provider_overrides:
        _apply_validator_overrides(provider_overrides.validators or {}, accum)
        _apply_insertion_overrides(provider_overrides.insertions or {}, accum)
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
