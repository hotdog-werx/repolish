from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

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
    ProviderContributions,
    TemplateMapping,
    call_provider_method,
)
from repolish.providers.models import (
    Provider as _ProviderBase,
)
from repolish.providers.models.template_path import RepolishTemplatePath

if TYPE_CHECKING:
    from repolish.config.models.provider import ProviderOverrides


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
    """Collect validator registrations for one provider."""
    validators = cast(
        'dict[str, dict[str, FileValidatorEntry]]',
        call_provider_method(inst, 'create_file_validators', own_ctx),
    )
    for path, path_validators in validators.items():
        accum.file_validators.setdefault(path, {}).update(path_validators)
        accum.validator_sources.setdefault(path, provider_id)


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
