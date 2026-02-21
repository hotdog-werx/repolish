"""Module-style provider utilities and adapter.

This module centralises logic that previously lived in `context.py` and
provides an adapter (`ModuleProviderAdapter`) that wraps a legacy
module-style provider dict and exposes the new-style `Provider` API.

The goal: let the rest of the loader operate on `Provider` instances only
while keeping a thin, well-tested conversion layer for module-style
providers.

NOTE: There are two pragma-no-cover blocks. These two in my opinion are not
worth covering given that this module will go away. It is only here to
support the transition period and the code paths in question are already well-covered.
"""

from __future__ import annotations

import warnings
from inspect import signature
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel as _BaseModel

from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.types import FileMode, TemplateMapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    # only used for type hints; annotations are strings so no runtime import
    from collections.abc import Callable as _Callable

    # aliases for legacy signatures
    CollectInputsSig = _Callable[
        [dict[str, object], list[tuple[str, object]], int],
        dict[str, object],
    ]
    FinalizeSig = _Callable[
        [
            dict[str, object],
            list[object],
            list[tuple[str, object]],
            int,
        ],
        object,
    ]

# --- lightweight helpers lifted from the old `context.py` ---------------------


def call_factory_with_context(
    factory: _Callable[..., object],
    context: dict[str, object],
) -> object:
    """Call a provider factory allowing 0 or 1 positional argument.

    Backwards-compatible: if the factory accepts no parameters it will be
    invoked without arguments. If it accepts one parameter the merged
    context dict is passed. Any other signature is rejected.
    """
    sig = signature(factory)
    params = len(sig.parameters)
    if params == 0:
        return factory()
    if params == 1:
        return factory(context)
    msg = f'Provider factory must accept 0 or 1 args, got {params}'
    raise TypeError(msg)


def extract_from_module_dict(
    module_dict: dict[str, object],
    name: str,
    *,
    expected_type: type | tuple[type, ...] | None = None,
    allow_callable: bool = True,
    default: object | None = None,
) -> object | None:
    """Generic extractor for attributes or factory callables from a module dict.

    - Prefer a callable factory when present and allowed.
    - Otherwise return a top-level attribute if present and of the expected type.
    - On any mismatch or exception the `default` is returned (or an exception
      is propagated for factory callables).
    """
    candidate = module_dict.get(name)
    if allow_callable and callable(candidate):
        val = cast('Callable[[], object]', candidate)()
        if expected_type is None or isinstance(val, expected_type):
            return val
        msg = f'{name}() returned wrong type: {type(val)!r}'
        raise TypeError(msg)

    if candidate is None:
        return default
    if expected_type is None or isinstance(candidate, expected_type):
        return candidate
    msg = f'module attribute {name!r} has wrong type: {type(candidate)!r}'
    raise TypeError(msg)


# --- helpers used by collect_contexts_with_provider_map ----------------------


def _collect_context_from_module(
    module_dict: dict[str, object],
    merged: dict[str, Any],
) -> None:
    """Collect and merge context from a single module dict into `merged`."""
    create_ctx = module_dict.get('create_context')
    if callable(create_ctx):
        val = call_factory_with_context(create_ctx, merged)
        if val is not None and not isinstance(val, dict):
            msg = 'create_context() must return a dict'
            raise TypeError(msg)
        if isinstance(val, dict):
            merged.update(cast('dict[str, Any]', val))
        return

    ctx_var = module_dict.get('context')
    if isinstance(ctx_var, dict):
        merged.update(cast('dict[str, Any]', ctx_var))


def _handle_callable_create_ctx(
    provider_id: str,
    create_ctx: _Callable,
    merged: dict[str, Any],
    provider_map: dict[str, object],
) -> None:
    """Call provider `create_context()` safely and record per-provider map.

    Emit a DeprecationWarning when a provider's `create_context()` returns
    ``None`` to preserve the historical behaviour and tests.
    """
    val = call_factory_with_context(create_ctx, merged)
    if val is not None and not isinstance(val, dict):
        msg = 'create_context() must return a dict'
        raise TypeError(msg)
    if isinstance(val, dict):
        _val = cast('dict[str, Any]', val)
        merged.update(_val)
        provider_map[provider_id] = _val
    else:
        # Backwards-compatible behaviour: returning None is accepted but
        # emit a deprecation warning so callers are informed.
        warnings.warn(
            'create_context() returning None is deprecated and will be removed in a future release; '
            'return a `dict` or Pydantic model instead.',
            DeprecationWarning,
            stacklevel=2,
        )
        provider_map[provider_id] = {}


def collect_contexts(
    module_cache: list[tuple[str, dict]],
    initial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 1: collect and merge contexts from providers.

    If `initial` is provided it will be used as the starting merged context
    so providers see those values when their `create_context()` factories
    are invoked. Returns the merged dict.
    """
    merged: dict[str, Any] = dict(initial or {})
    for _provider_id, module_dict in module_cache:
        _collect_context_from_module(module_dict, merged)
    return merged


def collect_contexts_with_provider_map(
    module_cache: list[tuple[str, dict]],
    initial: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, object]]:
    """Collect merged context and return per-provider contexts.

    Returns a tuple (merged_context, provider_contexts) where
    `provider_contexts` maps provider_id -> the value returned by that
    provider's `create_context()` or `context` variable (which may be either a
    dict or a Pydantic model).  An empty dict is stored when the provider did
    not supply any context.
    """
    merged: dict[str, Any] = dict(initial or {})
    provider_map: dict[str, object] = {}

    for provider_id, module_dict in module_cache:
        create_ctx = module_dict.get('create_context')
        if callable(create_ctx):
            _handle_callable_create_ctx(
                provider_id,
                create_ctx,
                merged,
                provider_map,
            )
            continue

        ctx_var = module_dict.get('context')
        if isinstance(ctx_var, dict):
            merged.update(ctx_var)
            provider_map[provider_id] = ctx_var
            continue

        provider_map[provider_id] = {}

    return merged, provider_map


# --- Adapter: expose a Provider instance for a legacy module dict ------------


class ModuleProviderAdapter(_ProviderBase):
    """Adapter that exposes the `Provider` interface for a module-style provider.

    The adapter captures references to the module's original callables at
    construction time so that later injection of wrapper factories into the
    module dict does not cause recursion.
    """

    def __init__(
        self,
        module_dict: dict[str, object],
        provider_id: str,
    ) -> None:
        self._module = module_dict
        self._provider_id = provider_id

        # Capture originals to avoid accidental recursion after injection
        self._orig_create_context = module_dict.get('create_context')
        self._orig_context_var = module_dict.get('context')
        self._orig_create_file_mappings = module_dict.get(
            'create_file_mappings',
        )
        self._orig_file_mappings_var = module_dict.get('file_mappings')
        self._orig_create_anchors = module_dict.get('create_anchors')
        self._orig_anchors_var = module_dict.get('anchors')
        # narrow types for original callables so later calls are typed
        # original callable might be anything; cast to our alias to satisfy
        # the type checker. runtime behaviour is unchanged.
        self._orig_collect_inputs: CollectInputsSig | None = cast(
            'CollectInputsSig | None',
            module_dict.get('collect_provider_inputs'),
        )
        self._orig_finalize: FinalizeSig | None = cast(
            'FinalizeSig | None',
            module_dict.get('finalize_context'),
        )
        self._orig_get_inputs_schema: Callable[[], object] | None = cast(
            'Callable[[], object] | None',
            module_dict.get('get_inputs_schema'),
        )
        # Deletion / create-only legacy hooks
        self._orig_create_delete_files = module_dict.get('create_delete_files')
        self._orig_delete_files_var = module_dict.get('delete_files')
        self._orig_create_create_only = module_dict.get(
            'create_create_only_files',
        )
        self._orig_create_only_var = module_dict.get('create_only_files')
        # provider_migrated / provider_name may be module-level variables
        self._orig_provider_name = module_dict.get('provider_name')

    def get_provider_name(self) -> str:
        """Return the provider name, falling back to ``provider_id`` if unset."""
        name = self._orig_provider_name
        if isinstance(name, str) and name:
            return name
        return str(self._provider_id)

    def create_context(
        self,
        ctx: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Call the underlying module `create_context()` optionally passing a context.

        The adapter accepts an optional context dict and forwards it to the
        original callable when appropriate (maintains backwards compatibility
        with module-style factories that accept 0 or 1 args).
        """
        if callable(self._orig_create_context):
            # ``call_factory_with_context`` returns ``object``; callers expect a
            # ``dict[str, object]`` so we cast here to satisfy the type checker.
            return cast(
                'dict[str, object]',
                call_factory_with_context(
                    cast('Callable[..., object]', self._orig_create_context),
                    ctx or {},
                ),
            )
        if isinstance(self._orig_context_var, dict):
            return cast('dict[str, object]', self._orig_context_var)
        return {}

    def collect_provider_inputs(
        self,
        _own_context: dict[str, object],
        _all_providers: list[tuple[str, object]],
        _provider_index: int,
    ) -> dict[str, object]:
        """Return a dict of inputs forwarded from module implementation."""
        if callable(self._orig_collect_inputs):
            # original callable signature unknown; trust caller to use correct args
            return self._orig_collect_inputs(
                _own_context,
                _all_providers,
                _provider_index,
            )
        return {}

    def finalize_context(
        self,
        _own_context: dict[str, object],
        _received_inputs: list[object],
        _all_providers: list[tuple[str, object]],
        _provider_index: int,
    ) -> dict[str, object]:
        """Invoke the provider finalize_context hook when available."""
        if callable(self._orig_finalize):
            return cast(
                'dict[str, object]',
                self._orig_finalize(
                    _own_context,
                    _received_inputs,
                    _all_providers,
                    _provider_index,
                ),
            )
        return _own_context

    def get_inputs_schema(self) -> type | None:
        """Return a pydantic model class that validates inputs, if provided."""
        if callable(self._orig_get_inputs_schema):
            return cast(
                'type | None',
                self._orig_get_inputs_schema(),
            )  # pragma: no cover - See comment on top of file
        return None

    # File helpers: delegate to module-level factories / vars when present
    def create_file_mappings(
        self,
        context: object,
    ) -> dict[str, str | TemplateMapping]:
        """Return normalized file_mappings for this provider.

        Behavior:
        - Start from module `create_file_mappings()` or `file_mappings` if present.
        - Augment with legacy `create_create_only_files`/`create_only_files` and
          `create_delete_files`/`delete_files` by converting those entries into
          `TemplateMapping` instances with the appropriate `FileMode`.
        - Preserve explicit mappings from `create_file_mappings()` (they take
          precedence over converted legacy lists).
        """
        merged: dict[str, str | TemplateMapping] = {}

        # merge each step using helpers for clarity
        self._merge_base_mappings(
            merged,
            context if isinstance(context, dict) else {},
        )
        self._merge_create_only_mappings(merged)
        self._merge_delete_mappings(merged)

        return merged

    def _merge_base_mappings(
        self,
        merged: dict[str, str | TemplateMapping],
        ctx: dict | None,
    ) -> None:
        """Populate `merged` from provider's explicit mapping APIs."""
        if callable(self._orig_create_file_mappings):
            val = call_factory_with_context(
                self._orig_create_file_mappings,
                ctx or {},
            )
            if isinstance(val, dict):
                merged.update(cast('dict[str, str | TemplateMapping]', val))
        elif isinstance(self._orig_file_mappings_var, dict):
            merged.update(
                cast(
                    'dict[str, str | TemplateMapping]',
                    self._orig_file_mappings_var,
                ),
            )

    def _merge_create_only_mappings(
        self,
        merged: dict[str, str | TemplateMapping],
    ) -> None:
        """Convert legacy create-only file lists into template mappings."""
        items = self._resolve_create_only_items()
        if not isinstance(items, (list, tuple, set)):
            return
        self._add_create_only_entries(merged, items)

    def _resolve_create_only_items(self) -> object | None:
        """Return the raw sequence of create-only entries from legacy APIs."""
        if callable(self._orig_create_create_only):
            return call_factory_with_context(
                self._orig_create_create_only,
                {},
            )
        if isinstance(self._orig_create_only_var, (list, tuple, set)):
            return list(self._orig_create_only_var)
        return None

    def _add_create_only_entries(
        self,
        merged: dict[str, str | TemplateMapping],
        co_items: list | tuple | set,
    ) -> None:
        """Append create-only entries to merged mappings."""
        for it in co_items:
            p = Path(*Path(str(it)).parts) if it else None
            if not p:
                continue
            key = p.as_posix()
            if key in merged:
                continue
            merged[key] = TemplateMapping(
                None,
                None,
                FileMode.CREATE_ONLY,
                source_provider=self._provider_id,
            )

    def _merge_delete_mappings(
        self,
        merged: dict[str, str | TemplateMapping],
    ) -> None:
        """Convert legacy delete-files callable into template mappings."""
        items = self._resolve_delete_items()
        if not items:
            return
        self._add_delete_entries(merged, items)

    def _resolve_delete_items(self) -> list | tuple | None:
        """Fetch raw delete entries from legacy factory, validating its type."""
        if not callable(self._orig_create_delete_files):
            return None

        val = call_factory_with_context(self._orig_create_delete_files, {})
        if val is None:
            return []
        if not isinstance(val, (list, tuple)):
            msg = 'create_delete_files() must return a list or tuple'
            raise TypeError(msg)
        return val

    def _add_delete_entries(
        self,
        merged: dict[str, str | TemplateMapping],
        del_items: list | tuple,
    ) -> None:
        """Append delete entries to merged mappings, validating each item."""
        for it in del_items:
            if not it:
                continue
            if not isinstance(it, (str, Path)):
                msg = f'Invalid delete_files entry: {it!r}'
                raise TypeError(msg)
            p = Path(*Path(str(it)).parts)
            key = p.as_posix()
            if key in merged:
                continue
            merged[key] = TemplateMapping(
                None,
                None,
                FileMode.DELETE,
                source_provider=self._provider_id,
            )

    def create_anchors(self, _ctx: dict | None = None) -> dict[str, str]:
        """Return anchors for this provider, delegating to module-level factory or var."""
        if callable(self._orig_create_anchors):
            return cast(
                'dict[str, str]',
                call_factory_with_context(
                    self._orig_create_anchors,
                    _ctx or {},
                ),
            )
        if isinstance(self._orig_anchors_var, dict):
            return cast('dict[str, str]', self._orig_anchors_var)
        return {}


def inject_provider_instance_for_module(
    module_dict: dict[str, object],
    provider_id: str,
) -> None:
    """Create and inject a ModuleProviderAdapter into `module_dict`.

    This mirrors the behaviour used for class-based providers so the rest of
    the loader can uniformly operate on module dicts that expose
    `_repolish_provider_instance` and module-level wrappers such as
    `create_context()`.
    """
    if module_dict.get('_repolish_provider_instance'):
        return

    inst = ModuleProviderAdapter(module_dict, provider_id)
    # Keep a reference for diagnostics / tests
    module_dict['_repolish_provider_instance'] = inst

    # Provide module-level wrapper for `create_context` only. Do NOT add
    # `create_file_mappings`/`create_anchors` keys when the original module
    # did not define them — that would hide validation errors such as
    # `require_file_mappings=True` which relies on the original presence.
    def _wrapper(_ctx: dict | None = None) -> dict | None:
        val = inst.create_context(_ctx)
        if isinstance(val, _BaseModel):
            return val.model_dump()  # pragma: no cover - See comment on top of file
        return val

    module_dict['create_context'] = _wrapper

    # Preserve any original module-level factory functions for mappings/anchors
    # — the adapter captured references to originals during construction and
    # will delegate to them as needed.
