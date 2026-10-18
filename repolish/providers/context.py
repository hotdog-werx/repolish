import copy
from typing import Any, TypeVar, cast

from repolish.providers._log import logger
from repolish.providers.models import BaseContext

T = TypeVar('T')


def apply_context_overrides(
    context: dict[str, Any],
    overrides: dict[str, Any],
) -> None:
    """Apply context overrides using dot-notation paths.

    Supports both flat dot-notation keys and nested dictionary structures.
    Nested structures are flattened to dot-notation before application.

    Modifies the context in-place. Logs warnings for invalid paths.
    """
    flattened = _flatten_override_dict(overrides)
    for path, value in flattened.items():
        _apply_override(context, path.split('.'), value)


def _flatten_override_dict(overrides: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested override dictionaries to dot-notation keys."""
    flattened = {}

    for key, value in overrides.items():
        if isinstance(value, dict):
            # Nested dict that needs flattening - use the key as prefix
            _flatten_nested_dict(value, key, flattened)
        else:
            # Simple key-value pair
            flattened[key] = value

    return flattened


def _flatten_nested_dict(
    nested: dict[str, Any],
    prefix: str,
    flattened: dict[str, Any],
) -> None:
    """Flatten a nested dictionary into the flattened dict."""
    for key, value in nested.items():
        full_key = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            _flatten_nested_dict(value, full_key, flattened)
        else:
            flattened[full_key] = value


def _apply_override(
    obj: object,
    path_parts: list[str],
    value: object,
) -> None:
    """Recursively apply an override at the given path."""
    if not path_parts:
        return  # Should not happen

    key = path_parts[0]
    remaining = path_parts[1:]

    if isinstance(obj, dict):
        _apply_override_to_dict(obj, key, remaining, value)
    elif isinstance(obj, list):
        _apply_override_to_list(obj, key, remaining, value)
    else:
        logger.warning(
            'context_override_cannot_navigate',
            key=key,
            current_type=type(obj).__name__,
        )


def _apply_override_to_dict(
    obj: dict,
    key: str,
    remaining: list[str],
    value: object,
) -> None:
    """Apply override to a dictionary."""
    if not remaining:
        obj[key] = value
        return
    if key not in obj:
        # Create intermediate dictionary for nested path navigation
        obj[key] = {}
    _apply_override(obj[key], remaining, value)


def _apply_override_to_list(
    obj: list,
    key: str,
    remaining: list[str],
    value: object,
) -> None:
    """Apply override to a list."""
    try:
        index = int(key)
        if 0 <= index < len(obj):
            if not remaining:
                obj[index] = value
                return
            _apply_override(obj[index], remaining, value)
        else:
            logger.warning(
                'context_override_index_out_of_range',
                index=index,
                list_length=len(obj),
            )
    except ValueError:
        logger.warning(
            'context_override_invalid_index',
            key=key,
            expected_integer=True,
        )


# ---------------------------------------------------------------------------
# Model-level override helpers
# ---------------------------------------------------------------------------


def _refacet_contexts(
    ctx: BaseContext,
    data: dict[str, object],
    facet_types: dict[str, type[BaseContext]],
    provider: str | None,
) -> None:
    """Re-validate each facet dict on ``ctx`` back into its runtime class.

    Companion to the override round-trip in :func:`_apply_overrides_to_model`:
    ``ctx.model_validate(data)`` reconstructs the ``facets`` map against its
    declared ``dict[str, BaseContext]`` type, so a facet context subclass
    (e.g. a gitignore facet carrying ``entries``) loses its specific fields.
    ``facet_types`` holds the runtime class of each facet as it lived on the
    pre-override context; the dump's facet dicts — with any dotted facet
    overrides applied — are re-validated into those classes and written back.
    A facet that fails validation keeps the base-coerced context and logs a
    warning, so one bad override never blocks the run.
    """
    facets_data = cast('dict[str, object]', data.get('facets') or {})
    for name, facet_cls in facet_types.items():
        try:
            ctx.facets[name] = facet_cls.model_validate(facets_data[name])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'facet_context_override_validation_failed',
                provider=provider,
                facet=name,
                error=str(exc),
            )


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

    # Facet contexts serialize by runtime type (BaseContext.facets carries a
    # field_serializer), but the ``facets`` field is declared as
    # ``dict[str, BaseContext]`` — plain re-validation below coerces each one
    # back to the declared base class, silently dropping every facet-specific
    # field (e.g. a gitignore facet's ``entries``). Snapshot the runtime
    # classes and re-validate each facet dict back into its own type, so a
    # context override round-trip keeps facet fields and dotted facet
    # overrides (``facets.<name>.<field>``) land on the real model.
    facet_types = {name: type(facet_ctx) for name, facet_ctx in getattr(ctx, 'facets', {}).items()}

    try:
        new_ctx = ctx.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            'context_override_validation_failed',
            provider=provider,
            error=str(exc),
        )
        return ctx

    _refacet_contexts(new_ctx, data, facet_types, provider=provider)

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
    provider_overrides: dict[str, dict[str, object]],
) -> None:
    """Apply per-provider overrides (handles BaseModel and dict contexts).

    Extracted helper to reduce duplication in the three-phase workflow.
    Behaviour mirrors :func:`_apply_overrides_to_provider_contexts` --
    failures are logged and the original context is preserved.
    """
    for pid, overrides in provider_overrides.items():
        ctx = provider_contexts.get(pid)
        if ctx:
            provider_contexts[pid] = _apply_overrides_to_model(
                ctx,
                overrides,
                provider=pid,
            )
