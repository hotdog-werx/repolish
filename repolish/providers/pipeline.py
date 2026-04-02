from __future__ import annotations

from typing import Any, cast

from repolish.pkginfo import resolve_package_identity
from repolish.providers._log import logger
from repolish.providers.models import (
    BaseContext,
    GlobalContext,
    ProviderEntry,
    ProviderInfo,
    ProviderSession,
)
from repolish.providers.models import Provider as _ProviderBase
from repolish.providers.models.context import RepolishContext


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
            # `alias` is the configuration key (here we mirror provider_id
            # since that's what create_providers passes).
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
                alias=alias,
                inst_type=inst_type,
                context=ctx_obj or BaseContext(),
                context_type=ctx_type,
                input_type=schema,
            ),
        )
    return all_providers_list


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
    except Exception as exc:  # noqa: BLE001 - don't let one provider stop the run
        logger.warning(
            'provider_create_context_raised',
            provider=pid,
            error=str(exc),
        )
        return

    if isinstance(ctx, BaseContext) and hasattr(ctx, 'repolish'):
        ctx = ctx.model_copy(update={'repolish': global_context})

    # inject provider identity so templates can reference {{ repolish.provider.alias }},
    # {{ repolish.provider.version }}, {{ repolish.provider.package_name }}, etc.
    if isinstance(ctx, BaseContext):
        mono = global_context.workspace
        member_name = '_root' if mono.mode == 'root' else ''
        member_path = '.'
        if mono.mode == 'member' and mono.package_dir is not None:
            for m in mono.members:
                if (mono.root_dir / m.path).resolve() == mono.package_dir.resolve():
                    member_name = m.name
                    member_path = m.path.as_posix()
                    break
        provider_info = ProviderInfo(
            alias=getattr(inst, 'alias', ''),
            version=getattr(inst, 'version', ''),
            package_name=getattr(inst, 'package_name', ''),
            project_name=getattr(inst, 'project_name', ''),
            session=ProviderSession(
                mode=mono.mode,
                member_name=member_name,
                member_path=member_path,
            ),
        )
        repolish_ctx = RepolishContext(
            repo=global_context.repo,
            year=global_context.year,
            workspace=global_context.workspace,
            provider=provider_info,
        )
        ctx = ctx.model_copy(update={'repolish': repolish_ctx})

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
        if inst is None:  # pragma: no cover - module-style providers have no class instance
            continue
        _synthesize_provider_context_for_pid(
            inst,
            pid,
            provider_contexts,
            global_context,
        )


def _set_provider_metadata(
    module_cache: list[tuple[str, dict]],
    instances: list[_ProviderBase | None],
    alias_map: dict[str, str],
) -> None:
    """Set alias, version, package_name and project_name on every provider instance.

    Version is read from the module's __version__ when present; falls back to
    an empty string for local / un-installed providers.
    package_name and project_name are derived from __package__ via
    :func:`repolish.pkginfo.resolve_package_identity`.
    """
    for _idx, (_pid, _mod) in enumerate(module_cache):
        _inst = instances[_idx]
        if _inst is not None:
            _inst.alias = alias_map.get(_pid, _pid)
            _inst.version = _mod.get('__version__', '') or ''
            _pkg, _proj = resolve_package_identity(_mod.get('__package__'))
            _inst.package_name = _pkg
            _inst.project_name = _proj
