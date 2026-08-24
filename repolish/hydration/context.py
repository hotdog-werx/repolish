from pathlib import Path, PurePosixPath

from repolish.config import RepolishConfig
from repolish.config.models.provider import (
    ProviderOverrides,
    ResolvedProviderInfo,
)
from repolish.misc import ctx_to_dict
from repolish.providers import Action, Decision, SessionBundle, create_providers
from repolish.providers.models import BaseInputs, GlobalContext, ProviderEntry
from repolish.providers.models.pipeline import ProviderContributions


def _collect_provider_overrides(
    config: RepolishConfig,
    alias_to_pid: dict[str, str],
) -> dict[str, ProviderOverrides]:
    """Collect ProviderOverrides objects keyed by provider ID.

    Only includes providers that have overrides defined.

    Args:
        config: The resolved configuration
        alias_to_pid: Mapping of provider alias to provider ID (posix path)

    Returns:
        Dict mapping provider ID to ProviderOverrides (only for providers with overrides)
    """
    overrides_by_pid: dict[str, ProviderOverrides] = {}

    for alias, info in config.providers.items():
        if info.overrides:
            pid = alias_to_pid.get(alias, info.provider_root.as_posix())
            overrides_by_pid[pid] = info.overrides

    return overrides_by_pid


def _build_alias_to_pid(config: RepolishConfig) -> dict[str, str]:
    """Return a mapping of provider alias -> loader provider id (posix path)."""
    alias_to_pid: dict[str, str] = {}
    for alias, info in config.providers.items():
        alias_to_pid[alias] = info.provider_root.as_posix()
    return alias_to_pid


def _build_override_maps(
    config: RepolishConfig,
    alias_to_pid: dict[str, str],
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, str]]]:
    """Return (provider_overrides, anchor_overrides) keyed by provider_id."""
    provider_overrides: dict[str, dict[str, object]] = {}
    anchor_overrides: dict[str, dict[str, str]] = {}
    for alias, info in config.providers.items():
        pid = alias_to_pid.get(alias, info.provider_root.as_posix())
        merged = _merge_context_overrides(info)
        if merged:
            provider_overrides[pid] = merged
        if info.overrides and info.overrides.anchors:
            anchor_overrides[pid] = info.overrides.anchors
    return provider_overrides, anchor_overrides


def _merge_context_overrides(info: ResolvedProviderInfo) -> dict[str, object]:
    """Merge context overrides from a provider info into a single dict."""
    merged: dict[str, object] = {}
    if not info.overrides:
        return merged
    if info.overrides.context_merge:
        merged.update(ctx_to_dict(info.overrides.context_merge))
    if info.overrides.context_dotted:
        merged.update(info.overrides.context_dotted)
    return merged


def _apply_delete_overrides(
    providers: SessionBundle,
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


def build_final_providers(
    config: RepolishConfig,
    *,
    global_context: GlobalContext | None = None,
    extra_provider_entries: list[ProviderEntry] | None = None,
    extra_inputs: list[BaseInputs] | None = None,
) -> SessionBundle:
    """Build the final SessionBundle object from all configured providers.

    - Loads providers from the directories referenced by configured providers.
    - Applies per-provider context and overrides from `config.providers[alias]`
      so that provider hooks see project-supplied values during execution.
    - Applies `config.delete_files` entries (with '!' negation) on top of
      provider decisions and records provenance Decisions for config entries.

    When *global_context* is supplied it is forwarded to ``create_providers``
    instead of calling ``get_global_context()`` — used by the monorepo
    orchestrator to inject a pre-built context that carries the
    ``MonorepoContext``.  *extra_provider_entries* and *extra_inputs* are
    forwarded to the pipeline for member-to-root input routing.
    """
    # build a per-provider override map from the project configuration.
    # the loader applies these via `_apply_provider_overrides` which uses
    # `apply_context_overrides` (dot-notation aware) and then re-validates
    # the model, so each provider's typed context is the single source of truth.
    alias_to_pid = _build_alias_to_pid(config)
    provider_overrides, anchor_overrides = _build_override_maps(
        config,
        alias_to_pid,
    )
    model_overrides = _collect_provider_overrides(config, alias_to_pid)

    all_override_pids = (
        set(provider_overrides)
        | set(anchor_overrides)
        | {pid for pid, ovr in model_overrides.items() if ovr.file_mappings}
        | {pid for pid, ovr in model_overrides.items() if ovr.validators}
        | {pid for pid, ovr in model_overrides.items() if ovr.insertions}
        | {pid for pid, ovr in model_overrides.items() if ovr.insertions_extend_files}
    )

    contributions = ProviderContributions(
        overrides={
            pid: ProviderOverrides(
                context_merge=provider_overrides.get(pid),
                anchors=anchor_overrides.get(pid),
                file_mappings=model_overrides[pid].file_mappings if pid in model_overrides else None,
                validators=model_overrides[pid].validators if pid in model_overrides else None,
                insertions=model_overrides[pid].insertions if pid in model_overrides else None,
                insertions_extend_files=(
                    model_overrides[pid].insertions_extend_files if pid in model_overrides else None
                ),
            )
            for pid in all_override_pids
        },
    )

    # determine directories from provider info (alias_to_pid holds the
    # normalized loader IDs constructed from target_dir)
    dirs: list[str | tuple[str, str]] = list(alias_to_pid.items())
    result = create_providers(
        dirs,
        contributions=contributions,
        global_context=global_context,
        extra_provider_entries=extra_provider_entries,
        extra_inputs=extra_inputs,
    )

    # build_final_providers always performs a full pass (dry_run=False),
    # so the result is always a SessionBundle object.
    assert isinstance(result, SessionBundle)  # noqa: S101 - guaranteed by dry_run=False
    providers = result

    delete_files = _apply_delete_overrides(providers, config)
    providers.delete_files = delete_files
    return providers
