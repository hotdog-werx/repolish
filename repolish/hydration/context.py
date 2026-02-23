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
    # construct per-provider override map that will be applied "early"
    # inside the loader.  this ensures provider hooks see project-supplied
    # values before they execute, matching the behaviour of the real
    # application.  ``create_providers`` will merge these into the
    # ``provider_contexts`` map before gathering inputs.
    # provider IDs used by the loader are just the directory path passed
    # to ``create_providers``; this is effectively ``info.target_dir``.
    # build a small alias->provider-id map that mirrors the one used when
    # resolving directories from providers.  when a provider specifies a
    # non-empty ``templates_dir`` the loader will receive a path that includes
    # that suffix, so the override key must match or the configuration will be
    # ignored.  ``_build_alias_to_pid`` already performs this computation, so
    # reuse it here rather than repeating the logic.
    alias_to_pid = _build_alias_to_pid(config)

    provider_overrides: dict[str, dict[str, object]] = {}
    for alias, info in config.providers.items():
        # prefer the canonical id from ``alias_to_pid``; fall back to the raw
        # ``target_dir`` if something went wrong (shouldn't happen for a
        # resolved config, but defensive code is cheap).
        pid = alias_to_pid.get(alias, info.target_dir.as_posix())

        merged: dict[str, object] = {}
        if info.context:
            merged.update(ctx_to_dict(info.context))
        if info.context_overrides:
            merged.update(info.context_overrides)
        if merged:
            provider_overrides[pid] = merged

    providers = create_providers(
        [str(d) for d in config.directories],
        base_context=config.context,
        context_overrides=config.context_overrides,
        provider_overrides=provider_overrides,
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
