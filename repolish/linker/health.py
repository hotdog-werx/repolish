"""Provider readiness checks and registration.

The central contract: `repolish.yaml` is the source of truth for *which*
providers exist; `.repolish/_/provider-info.<alias>.json` is the "registered"
cache that tells repolish *where* their resources live.

:func:`ensure_providers_ready` is the single entry point used by both
`repolish apply` and `repolish link` to guarantee that every provider is
registered before any operation that depends on resolved paths. `link` runs
with ``verify_locations`` enabled: it probes each CLI provider for its
current package location and re-registers only the ones that moved, so a
plain `repolish link` (no ``--force``) both detects dev ↔ release switches
and costs a single subprocess per provider instead of two.
"""

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from hotlog import get_logger

from repolish.cli_registry import probe_provider_info
from repolish.config import ProviderConfig
from repolish.config.models.metadata import ProviderFileInfo
from repolish.config.models.provider import ModuleProviderConfig
from repolish.config.providers import load_provider_info
from repolish.exceptions import ModuleLinkError, ProviderNotReadyError
from repolish.linker.module_link import probe_module_info
from repolish.linker.orchestrator import process_provider
from repolish.linker.providers import (
    link_target_current,
    locations_match,
    write_provider_info_file,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class SoundnessIssue:
    """One failed soundness check for a module-declared provider.

    *detail* states what was observed, *recovery* the next command a user
    should run. Both are plain text so a raised report reads as steps,
    not stack traces.
    """

    alias: str
    module: str
    kind: str
    """``module_unimportable`` or ``stale_location``."""
    detail: str
    recovery: str


@dataclass
class ProviderReadinessResult:
    """Outcome of an :func:`ensure_providers_ready` call."""

    ready: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    soundness_issues: list[SoundnessIssue] = field(default_factory=list)
    """Failed module-provider soundness checks (see :func:`audit_context_soundness`).

    Readiness alone only says the provider registered; these say the
    registration agrees with the live environment. File-writing runs must
    refuse to proceed when any are present: the alternative is silently
    rendering degraded generated headers."""

    @property
    def all_ready(self) -> bool:
        """True when every requested provider was successfully registered."""
        return not self.failed


def _resolve_path(path: str, config_dir: Path) -> Path:
    p = Path(path)
    return p.resolve() if p.is_absolute() else (config_dir / p).resolve()


def _paths_valid(info: ProviderFileInfo) -> bool:
    """Return True only when every path recorded in *info* actually exists."""
    if not Path(info.resources_dir).exists():
        return False
    return not (info.provider_root and not Path(info.provider_root).exists())


def _register_static(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> ProviderFileInfo | None:
    """Write a provider-info file from the YAML `provider_root`/`resources_dir` fields.

    Returns the written `ProviderFileInfo`, or `None` when the path does
    not exist and registration cannot proceed.
    """
    # guaranteed by ProviderConfig validator: provider_root is set when cli is absent,
    # and the CLI fallback path guards with `if provider_config.provider_root` before calling here
    provider_root_abs = _resolve_path(
        cast('str', provider_config.provider_root),
        config_dir,
    )

    if not provider_root_abs.exists():
        logger.warning(
            'static_provider_root_missing',
            alias=alias,
            provider_root=str(provider_root_abs),
            suggestion='check provider_root in repolish.yaml',
        )
        return None

    resources_abs = (
        _resolve_path(provider_config.resources_dir, config_dir)
        if provider_config.resources_dir
        else provider_root_abs
    )

    provider_info = ProviderFileInfo(
        resources_dir=str(resources_abs),
        provider_root=str(provider_root_abs),
    )
    write_provider_info_file(alias, provider_info, config_dir)
    logger.info(
        'static_provider_registered',
        alias=alias,
        provider_root=str(provider_root_abs),
        resources_dir=str(resources_abs),
        _display_level=1,
    )
    return provider_info


def _static_paths_current(
    info: ProviderFileInfo,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> bool:
    """Return whether cached info matches the paths implied by the current config.

    Editing ``provider_root``/``resources_dir`` in ``repolish.yaml`` changes
    where a static provider lives even though the previously recorded paths
    still exist on disk — so the cache must be compared against the config,
    not just against the filesystem.
    """
    # guaranteed by ProviderConfig validator: provider_root is set when cli is absent
    provider_root_abs = _resolve_path(
        cast('str', provider_config.provider_root),
        config_dir,
    )
    resources_abs = (
        _resolve_path(provider_config.resources_dir, config_dir)
        if provider_config.resources_dir
        else provider_root_abs
    )
    return (
        Path(info.resources_dir) == resources_abs
        and Path(
            info.provider_root,
        )
        == provider_root_abs
    )


def _cache_lookup(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
    *,
    verify_locations: bool,
) -> tuple[ProviderFileInfo | None, bool]:
    """Load the cached info and decide whether it can be trusted as-is.

    Returns ``(previous_info, cache_hit)``:

    - ``cache_hit`` True: the cache is current, registration is skipped.
    - ``previous_info`` set but no hit: the info is valid on disk but may be
      stale — hand it to registration so the CLI runner can probe first.
    - Both empty: no usable cache; register from scratch.
    """
    info = load_provider_info(alias, config_dir)
    if info is None:
        return None, False
    if not _paths_valid(info):
        logger.warning(
            'provider_info_stale',
            alias=alias,
            resources_dir=info.resources_dir,
            provider_root=info.provider_root or '(same as resources_dir)',
            reason='recorded paths no longer exist; re-registering',
        )
        return None, False
    if not provider_config.cli and not provider_config.module:
        # Static provider: the config is the source of truth for location.
        if _static_paths_current(info, provider_config, config_dir):
            logger.debug('provider_already_ready', alias=alias)
            return info, True
        logger.warning(
            'static_provider_moved',
            alias=alias,
            recorded=info.resources_dir,
            reason='provider_root/resources_dir changed in repolish.yaml; re-registering',
        )
        return None, False
    if not verify_locations:
        # No probe requested (e.g. `repolish apply`): trust recorded paths;
        # `repolish link` is the refresh point for provider locations.
        logger.debug('provider_already_ready', alias=alias)
        return info, True
    # CLI or module provider under location verification: the info file is
    # valid, but only a probe can tell whether the package still lives
    # where it says.
    return info, False


def _register_provider(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
    *,
    location_context: str | None = None,
    fresh_info: ProviderFileInfo | None = None,
) -> bool:
    """Attempt to (re-)register a single provider.

    Module and CLI registration both go through
    :func:`~repolish.linker.orchestrator.process_provider` (module first,
    CLI as its fallback); a failure falls back to static paths. The CLI
    fallback is part of the v2 removal boundary (see
    :mod:`repolish.cli_registry`).
    Returns True on success.
    """
    if provider_config.module or provider_config.cli:
        exit_code = process_provider(
            alias,
            provider_config,
            config_dir,
            location_context=location_context,
            fresh_info=fresh_info,
        )
        if exit_code == 0:
            return True
        # Module/CLI failed; fall back to static paths if available
        if provider_config.provider_root:
            logger.warning(
                'provider_cli_failed_falling_back',
                alias=alias,
                cli=provider_config.cli,
                reason='link failed; using provider_root as fallback',
            )
            return _register_static(alias, provider_config, config_dir) is not None
        return False

    return _register_static(alias, provider_config, config_dir) is not None


def _probe_module_or_cli(
    provider_config: ProviderConfig,
    config_dir: Path,
    *,
    location_context: str | None = None,
) -> ProviderFileInfo:
    """Probe the provider's current location: in-process for ``module:``.

    Raises the same exceptions both paths surface upward:
    :exc:`~repolish.exceptions.ModuleLinkError` for a module that cannot be
    located, and the subprocess errors from the CLI ``--info`` probe.

    The ``cli:`` half is the v2 removal boundary: it goes together with
    :mod:`repolish.cli_registry` and the ``cli:`` config field.
    """
    if provider_config.module:
        return probe_module_info(provider_config.module, config_dir)
    return probe_provider_info(
        cast('str', provider_config.cli),
        location_context=location_context,
    )


def _probe_or_register(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
    previous_info: ProviderFileInfo,
    *,
    location_context: str | None = None,
) -> tuple[bool, bool]:
    """Verify a cached provider with one probe before registering.

    Module providers probe in-process (no subprocess, no JSON); CLI
    providers keep the ``--info`` subprocess probe. When the probe reports
    the same locations as the cache and the resources link still points at
    the package, the link step is skipped entirely — the provider is
    genuinely current. Otherwise the probe result is handed to registration
    so the probe is not run twice.
    """
    try:
        fresh = _probe_module_or_cli(
            provider_config,
            config_dir,
            location_context=location_context,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, ModuleLinkError):
        # Probe failed (module not importable, CLI missing or broken): fall
        # through to normal registration, which logs the failure and applies
        # the static fallback.
        registered = _register_provider(
            alias,
            provider_config,
            config_dir,
            location_context=location_context,
        )
        return registered, False
    if locations_match(fresh, previous_info) and link_target_current(
        previous_info,
    ):
        logger.info(
            'provider_link_unchanged',
            alias=alias,
            target=previous_info.resources_dir,
            _display_level=1,
        )
        return True, True
    registered = _register_provider(
        alias,
        provider_config,
        config_dir,
        location_context=location_context,
        fresh_info=fresh,
    )
    return registered, False


def _check_or_register(  # noqa: PLR0913 - mirrors ensure_providers_ready's parameter set
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
    *,
    force: bool,
    verify_locations: bool,
    location_context: str | None = None,
) -> tuple[bool, bool]:
    """Return (is_ready, was_cached) for the provider."""
    if force:
        registered = _register_provider(
            alias,
            provider_config,
            config_dir,
            location_context=location_context,
        )
        return registered, False
    previous_info, cache_hit = _cache_lookup(
        alias,
        provider_config,
        config_dir,
        verify_locations=verify_locations,
    )
    if cache_hit:
        return True, True
    if previous_info is not None and (provider_config.cli or provider_config.module):
        return _probe_or_register(
            alias,
            provider_config,
            config_dir,
            previous_info,
            location_context=location_context,
        )
    registered = _register_provider(
        alias,
        provider_config,
        config_dir,
        location_context=location_context,
    )
    return registered, False


def ensure_providers_ready(  # noqa: PLR0913 - need to pass all args through
    aliases: list[str],
    providers: dict[str, ProviderConfig],
    config_dir: Path,
    *,
    force: bool = False,
    strict: bool = False,
    location_context: str | None = None,
    verify_locations: bool = False,
) -> ProviderReadinessResult:
    """Ensure every provider is registered and its cached paths are valid.

    For each provider alias (in order):

    1. Load the provider-info file if it exists.
    2. Quick-check that the recorded paths still exist on disk.
    3. If the info is present and valid (and *force* is False) → ready, skip.
    4. Otherwise attempt (re-)registration:
       - CLI providers run their link command (``--info`` + link).
       - Static providers write a provider-info from ``provider_root`` /
         ``resources_dir`` in ``repolish.yaml``.
    5. Record the alias as ready or failed.

    With *verify_locations* (used by ``repolish link``), CLI providers whose
    cache looks valid are additionally probed via ``<cli> --info`` and module
    providers in-process: when the package still lives where the cache says
    and the resources link is intact, the link step is skipped; when it moved
    (dev ↔ release switch), the provider is re-registered. Static providers
    are always checked against the config-derived paths, which costs nothing.

    Args:
        aliases: Provider aliases to process, in the desired order.
        providers: Raw :class:`ProviderConfig` map from the config file.
        config_dir: Directory containing ``repolish.yaml``.
        force: Re-register even when an existing info file is valid.
            Used by ``repolish link --force`` to always refresh registrations.
        strict: Raise :exc:`~repolish.exceptions.ProviderNotReadyError`
            when any provider could not be registered.  Use for CI.
        location_context: Optional context string for monorepo awareness
            (e.g., 'root', 'packages/package_a'). Passed to provider CLIs
            via REPOLISH_LINK_CONTEXT environment variable.
        verify_locations: Probe CLI providers for their current package
            location instead of trusting the cache.  ``repolish link`` sets
            this; ``repolish apply`` leaves it off to stay fast.

    Returns:
        :class:`ProviderReadinessResult` with ``ready`` and ``failed`` lists.

    Raises:
        ProviderNotReadyError: When *strict* is True and any provider failed.

    Soundness issues are not raised here: they are collected on the
    returned :class:`ProviderReadinessResult` (``soundness_issues``) and
    logged as error events, so ``repolish link`` can report them alongside
    its summary tree. File-writing runs refuse to proceed with issues
    present (:func:`repolish.commands.apply.pipeline.resolve_session`
    raises :class:`~repolish.exceptions.ContextUnsoundError`).
    """
    result = ProviderReadinessResult()

    for alias in aliases:
        if alias not in providers:
            logger.warning('provider_not_in_config', alias=alias)
            continue

        ready, cached = _check_or_register(
            alias,
            providers[alias],
            config_dir,
            force=force,
            verify_locations=verify_locations,
            location_context=location_context,
        )
        if ready:
            result.ready.append(alias)
            if cached:
                result.cached.append(alias)
        else:
            logger.warning(
                'provider_not_ready',
                alias=alias,
                suggestion='run `repolish link` or verify provider_root in repolish.yaml',
            )
            result.failed.append(alias)

    result.soundness_issues = audit_context_soundness(
        aliases,
        providers,
        config_dir,
    )
    _log_soundness_issues(result.soundness_issues)

    if strict and result.failed:
        msg = f'providers not ready: {", ".join(result.failed)}'
        raise ProviderNotReadyError(msg)

    return result


def audit_context_soundness(
    aliases: list[str],
    providers: dict[str, ProviderConfig],
    config_dir: Path,
) -> list[SoundnessIssue]:
    """Audit every module-declared provider against the live environment.

    For each ``module:`` provider: the module must be importable, and the
    registered locations must match where the module currently lives. A
    provider that fails either renders generated headers degraded to its
    alias (identity falls back when the linked code is not what this
    environment imports), so callers stop the run instead.

    Providers whose registration the readiness loop already failed (no
    cached info) are skipped for the location check: their failure is
    reported through the normal readiness path. An unimportable module is
    always reported, though: ``module:`` declares that this environment
    provides the package, so a missing one is unsound no matter what
    registered. The one exception is a ``cli:`` co-declaration, where a
    module-probe failure is the documented fallback trigger, not a
    soundness violation.
    """
    issues: list[SoundnessIssue] = []
    for alias in aliases:
        provider_config = providers.get(alias)
        if provider_config is None or provider_config.module is None:
            continue
        if provider_config.cli:
            # module+cli: the CLI fallback governs registration; leave its
            # semantics alone (cli: is v2 removal scope).
            continue
        issues.extend(
            _audit_module_provider(alias, provider_config.module, config_dir),
        )
    return issues


def _audit_module_provider(
    alias: str,
    module: ModuleProviderConfig,
    config_dir: Path,
) -> list[SoundnessIssue]:
    """Run the soundness checks for one module provider."""
    try:
        fresh = probe_module_info(module, config_dir)
    except ModuleLinkError as exc:
        return [
            SoundnessIssue(
                alias=alias,
                module=module.name,
                kind='module_unimportable',
                detail=(
                    f'{module.name!r} is not importable from this '
                    f'environment ({sys.prefix}); the provider package is '
                    f'missing or broken: {exc}'
                ),
                recovery=(
                    'reinstall the provider package (re-run the '
                    'environment setup, e.g. `mise run setup` or '
                    '`uv sync`), then `repolish link`'
                ),
            ),
        ]

    cached = load_provider_info(alias, config_dir)
    if cached is None or locations_match(fresh, cached):
        # No cached registration: the readiness loop already reported the
        # failure. A registration matching where the environment imports the
        # module is sound.
        return []
    return [
        SoundnessIssue(
            alias=alias,
            module=module.name,
            kind='stale_location',
            detail=(
                'the registered provider does not match where this '
                f'environment imports {module.name!r} (registered: '
                f'{cached.site_package_dir or cached.provider_root}, '
                f'active: {fresh.site_package_dir})'
            ),
            recovery='`repolish link`',
        ),
    ]


def _log_soundness_issues(issues: list[SoundnessIssue]) -> None:
    """Record every soundness issue as an error event with its recovery."""
    for issue in issues:
        logger.error(
            'context_unsound',
            provider=issue.alias,
            module=issue.module,
            reason=issue.kind,
            detail=issue.detail,
            recovery=issue.recovery,
        )


def soundness_report(issues: list[SoundnessIssue]) -> str:
    """Format issues into the user-facing recovery report."""
    lines = [
        'repolish context is unsound; stopped before touching any files.',
        '',
    ]
    for issue in issues:
        lines.append(
            f'- provider {issue.alias!r} (module {issue.module!r}): {issue.detail}.',
        )
        lines.append(f'  recovery: {issue.recovery}')
    lines.extend(
        [
            '',
            (
                'If `repolish link` cannot repair a provider, remove the '
                '.repolish directory and re-run the environment setup: every '
                'registration is rebuilt from scratch on the next run.'
            ),
        ],
    )
    return '\n'.join(lines)
