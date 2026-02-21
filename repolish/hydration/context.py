from pathlib import Path, PurePosixPath

from repolish.config import RepolishConfig
from repolish.loader import Action, Decision, Providers, create_providers
from repolish.loader.context import apply_context_overrides
from repolish.misc import ctx_to_dict


def _build_alias_to_pid(config: RepolishConfig) -> dict[str, str]:
    """Return a mapping of provider alias -> loader provider id (posix path).

    Falls back to an empty mapping when no `config.providers` are defined.
    """
    alias_to_pid: dict[str, str] = {}
    if not config.providers:
        return alias_to_pid

    for alias, info in config.providers.items():
        alias_to_pid[alias] = (info.target_dir / info.templates_dir).as_posix()
    return alias_to_pid


def _merge_provider_contexts(
    providers: Providers,
    config: RepolishConfig,
    alias_to_pid: dict[str, str],
) -> dict[str, object]:
    """Merge provider-scoped contexts into a single merged context.

    This updates `providers.provider_contexts` in-place and returns the
    computed merged context starting from the loader-provided values.
    """
    merged_context: dict[str, object] = dict(providers.context)
    if not config.providers:
        return merged_context

    for alias, info in config.providers.items():
        pid = alias_to_pid.get(alias, alias)

        existing = providers.provider_contexts.get(pid)
        merged = dict(ctx_to_dict(existing))

        if info.context:
            merged.update(ctx_to_dict(info.context))

        if info.context_overrides:
            apply_context_overrides(merged, info.context_overrides)

        providers.provider_contexts[pid] = merged
        merged_context.update(merged)

    return merged_context


def _apply_global_overrides(
    merged_context: dict[str, object],
    config: RepolishConfig,
) -> None:
    """Apply project-level dotted overrides and final context into merged_context."""
    if config.context_overrides:
        apply_context_overrides(merged_context, config.context_overrides)

    merged_context.update(config.context)


def _apply_delete_overrides(
    providers: Providers,
    config: RepolishConfig,
) -> list[Path]:
    """Apply `config.delete_files` on top of provider delete decisions.

    Returns the final list of delete file paths (as Path-like objects).
    Also updates `providers.delete_history` with provenance decisions coming
    from `config.config_dir`.
    """
    delete_set = set(providers.delete_files)

    cfg_delete = config.delete_files or []
    for raw in cfg_delete:
        neg = isinstance(raw, str) and raw.startswith('!')
        entry = raw[1:] if neg else raw
        p = Path(*PurePosixPath(entry).parts)
        if neg:
            delete_set.discard(p)
        else:
            delete_set.add(p)

        src = config.config_dir.as_posix()
        providers.delete_history.setdefault(p.as_posix(), []).append(
            Decision(
                source=src,
                action=(Action.keep if neg else Action.delete),
            ),
        )

    return list(delete_set)


def build_final_providers(config: RepolishConfig) -> Providers:
    """Build the final Providers object by merging provider contributions.

    - Loads providers from config.directories
    - Applies per-provider context overrides defined in ``config.providers[alias].context``
      before merging, giving project config fine-grained control over each
      provider's values.
    - Merges config.context over provider.context
    - Applies config.delete_files entries (with '!' negation) on top of
      provider decisions and records provenance Decisions for config entries
    """
    providers = create_providers(
        [str(d) for d in config.directories],
        base_context=config.context,
        context_overrides=config.context_overrides,
    )

    alias_to_pid = _build_alias_to_pid(config)
    merged_context = _merge_provider_contexts(providers, config, alias_to_pid)
    _apply_global_overrides(merged_context, config)

    delete_files = _apply_delete_overrides(providers, config)

    # produce final Providers-like object.  Preserve provider-specific
    # metadata from the loader so callers can make migration decisions and
    # renderers can perform provider-scoped template contexts.
    return Providers(
        context=merged_context,
        anchors=providers.anchors,
        delete_files=delete_files,
        delete_history=providers.delete_history,
        file_mappings=providers.file_mappings,
        create_only_files=providers.create_only_files,
        provider_contexts=providers.provider_contexts,
        provider_migrated=providers.provider_migrated,
    )
