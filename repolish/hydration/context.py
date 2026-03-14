from pathlib import Path, PurePosixPath

from repolish.config import RepolishConfig
from repolish.loader import Action, Decision, Providers, create_providers
from repolish.misc import ctx_to_dict


def _build_alias_to_pid(config: RepolishConfig) -> dict[str, str]:
    """Return a mapping of provider alias -> loader provider id (posix path)."""
    alias_to_pid: dict[str, str] = {}
    for alias, info in config.providers.items():
        alias_to_pid[alias] = info.provider_root.as_posix()
    return alias_to_pid


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
    """Build the final Providers object from all configured providers.

    - Loads providers from the directories referenced by configured providers.
    - Applies per-provider context and overrides from `config.providers[alias]`
      so that provider hooks see project-supplied values during execution.
    - Applies `config.delete_files` entries (with '!' negation) on top of
      provider decisions and records provenance Decisions for config entries.
    """
    # build a per-provider override map from the project configuration.
    # the loader applies these via `_apply_provider_overrides` which uses
    # `apply_context_overrides` (dot-notation aware) and then re-validates
    # the model, so each provider's typed context is the single source of truth.
    alias_to_pid = _build_alias_to_pid(config)

    provider_overrides: dict[str, dict[str, object]] = {}
    for alias, info in config.providers.items():
        # prefer the canonical id from `alias_to_pid`; fall back to the raw
        # `provider_root` if something went wrong (shouldn't happen for a
        # resolved config, but defensive code is cheap).
        pid = alias_to_pid.get(alias, info.provider_root.as_posix())

        merged: dict[str, object] = {}
        if info.context:
            merged.update(ctx_to_dict(info.context))
        if info.context_overrides:
            merged.update(info.context_overrides)
        if merged and pid:
            provider_overrides[pid] = merged

    # determine directories from provider info (alias_to_pid holds the
    # normalized loader IDs constructed from target_dir)
    # type is union because create_providers accepts either plain strings or
    # (alias,path) tuples.  we only provide strings here, hence the explicit
    # annotation to satisfy the type checker.
    # pass (alias, pid) tuples so the loader can assign the config key to
    # Provider.alias before create_context is called.
    dirs: list[str | tuple[str, str]] = list(alias_to_pid.items())
    providers = create_providers(
        dirs,
        provider_overrides=provider_overrides,
    )

    delete_files = _apply_delete_overrides(providers, config)
    providers.delete_files = delete_files
    return providers
