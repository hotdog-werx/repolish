"""Lean configuration for fast lane runs.

A lane run does not need what a full ``repolish apply`` needs from
``repolish.yaml``: the provider's own location comes from its package (the
CLI is running from it right now), so provider registration, readiness
checks, and link subprocesses are pure overhead, and no other provider is
ever loaded. :func:`prepare_lane_config` builds the run's configuration
from a single raw YAML read — honoring only ``paused_files``, the
``fast_lanes`` section, ``template_overrides``, and the provider's own
entry fields — or entirely in memory when the project has no
``repolish.yaml`` or does not list the provider.
"""

from __future__ import annotations

from pathlib import Path

from hotlog import get_logger

from repolish.commands.apply.options import LaneSessionConfig
from repolish.config import RepolishConfig, load_config_file
from repolish.config.models.project import FastLanesSection, RepolishConfigFile
from repolish.config.models.provider import ProviderConfig, ResolvedProviderInfo

logger = get_logger(__name__)


def _package_name(provider_root: Path) -> str:
    """Fallback alias: the name of the package holding the provider resources.

    ``provider_root`` is ``<pkg>/resources/templates``, so the package
    directory is two levels up. The alias passed to ``provider_cli(alias=)``
    is the stable, provider-owned identity; this fallback only gives
    unregistered runs a sensible bookkeeping name.
    """
    return provider_root.parent.parent.name


def _match_entry(
    raw: RepolishConfigFile,
    provider_root: Path,
    config_dir: Path,
) -> tuple[str | None, ProviderConfig | None]:
    """Return the config entry (alias, raw entry) whose provider_root is *provider_root*.

    Matching mirrors what the full apply CLI does when it registers a
    provider: the entry that points at this package's ``resources/templates``
    directory belongs to this provider.
    """
    wanted = provider_root.resolve()
    for name, entry in raw.providers.items():
        declared_str = entry.provider_root
        if declared_str is not None:
            declared = Path(declared_str)
            if not declared.is_absolute():
                declared = config_dir / declared
            if declared.resolve() == wanted:
                return name, entry
    return None, None


def _resolve_identity(
    raw: RepolishConfigFile | None,
    alias: str | None,
    provider_root: Path,
    config_dir: Path,
) -> tuple[str, ProviderConfig | None]:
    """Pick the run's alias and the config entry contributing its fields.

    An explicit alias always wins; it is the provider-owned identity and does
    not have to appear in the config. Otherwise the entry whose
    ``provider_root`` points at this package names the run, and with no match
    at all the package name is the bookkeeping fallback.
    """
    final_alias = alias
    entry: ProviderConfig | None = None
    if raw is not None:
        if alias is not None and alias in raw.providers:
            entry = raw.providers[alias]
        else:
            matched_name, matched_entry = _match_entry(
                raw,
                provider_root,
                config_dir,
            )
            entry = matched_entry
            if final_alias is None:
                final_alias = matched_name
    if final_alias is None:
        final_alias = _package_name(provider_root)
        logger.debug(
            'lane_alias_fallback',
            alias=final_alias,
            suggestion='pass alias= to provider_cli for a stable identity',
        )
    return final_alias, entry


def _select_post_process(
    raw: RepolishConfigFile | None,
    lane: str | None,
    *,
    cli_name: str,
) -> list[str]:
    """Return the commands the run's post-process step should execute.

    ``all`` mirrors a full provider pass: the project's commands apply.
    A named lane runs only its own ``fast_lanes.config`` commands, and a
    lane with no entry runs none at all: a python-only lane never runs the
    project's dprint just because the project does.
    """
    if raw is None:
        return []
    if lane is None:
        return raw.post_process
    lane_key = f'{cli_name}:{lane}'
    lane_config = raw.fast_lanes.config.get(lane_key)
    return lane_config.post_process if lane_config is not None else []


def prepare_lane_config(
    provider_root: Path,
    lane: str | None,
    *,
    cli_name: str,
    alias: str | None,
    config_path: Path,
) -> LaneSessionConfig:
    """Build the single-provider configuration for one lane run.

    The provider's entry is always constructed in memory from the located
    root (the package the CLI is running from); a matching ``repolish.yaml``
    entry contributes its per-provider fields (symlinks, copies, overrides,
    ``resources_dir``). Project-wide keys are honored when the config file
    exists, whether or not the provider is listed in it.

    Post process selection: a named lane runs only its own
    ``fast_lanes.config[<lane>].post_process`` commands (none when unset) —
    the project's top-level ``post_process`` never applies to a named lane.
    ``all`` (``lane=None``) mirrors a full provider pass and runs the
    project's commands.

    Args:
        provider_root: The provider's ``resources/templates`` directory
            (from :func:`~repolish.fastlane.cli._locate_provider_root`).
        lane: The lane being run, or ``None`` for the provider's full pass.
        cli_name: Invoked CLI executable name. Used to scope
            ``fast_lanes.config`` keys as ``"<cli-name>:<lane-or-command>"``.
        alias: Explicit provider identity from ``provider_cli(alias=)``;
            always wins, and does not have to appear in the config.
        config_path: The ``--config`` path; may not exist.

    Returns:
        A :class:`~repolish.commands.apply.options.LaneSessionConfig` ready
        to pass as ``ApplyOptions.lane_config``.
    """
    config_dir = config_path.resolve().parent

    raw: RepolishConfigFile | None = None
    if config_path.is_file():
        raw = load_config_file(config_path)
        config_dir = config_path.resolve().parent

    final_alias, entry = _resolve_identity(
        raw,
        alias,
        provider_root,
        config_dir,
    )
    post_process = _select_post_process(raw, lane, cli_name=cli_name)

    paused_files: list[str] = []
    template_overrides: dict[str, str | None] = {}
    fast_lanes = FastLanesSection()
    if raw is not None:
        paused_files = raw.paused_files
        template_overrides = raw.template_overrides
        fast_lanes = raw.fast_lanes

    resources_dir = provider_root.parent
    if entry is not None and entry.resources_dir:
        declared = Path(entry.resources_dir)
        resources_dir = declared if declared.is_absolute() else (config_dir / declared).resolve()

    resolved = ResolvedProviderInfo(
        alias=final_alias,
        provider_root=provider_root,
        resources_dir=resources_dir,
        symlinks=entry.symlinks if entry is not None and entry.symlinks is not None else [],
        overrides=entry.overrides if entry is not None else None,
    )
    config = RepolishConfig(
        config_dir=config_dir,
        post_process=post_process,
        providers={final_alias: resolved},
        providers_order=[final_alias],
        template_overrides=template_overrides,
        paused_files=paused_files,
        fast_lanes=fast_lanes,
    )
    # An unlisted provider keeps the raw defaults for symlinks/copies: the
    # collectors fall back to the declarations in the provider's repolish.py.
    raw_providers = (
        {final_alias: entry}
        if entry is not None
        else {
            final_alias: ProviderConfig(provider_root=str(provider_root)),
        }
    )
    return LaneSessionConfig(config=config, raw_providers=raw_providers)
