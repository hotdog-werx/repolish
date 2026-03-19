"""Provider readiness checks and registration.

The central contract: `repolish.yaml` is the source of truth for *which*
providers exist; `.repolish/_/provider-info.<alias>.json` is the "registered"
cache that tells repolish *where* their resources live.

:func:`ensure_providers_ready` is the single entry point used by both
`repolish apply` and `repolish link` to guarantee that every provider is
registered before any operation that depends on resolved paths.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from hotlog import get_logger

from repolish.config import ProviderConfig
from repolish.config.models.metadata import ProviderFileInfo
from repolish.config.providers import load_provider_info
from repolish.exceptions import ProviderNotReadyError
from repolish.linker.orchestrator import process_provider
from repolish.linker.providers import write_provider_info_file

logger = get_logger(__name__)


@dataclass
class ProviderReadinessResult:
    """Outcome of an :func:`ensure_providers_ready` call."""

    ready: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

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


def _register_provider(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> bool:
    """Attempt to (re-)register a single provider.

    Tries the CLI first (when set), then falls back to static paths.
    Returns True on success.
    """
    if provider_config.cli:
        exit_code = process_provider(alias, provider_config, config_dir)
        if exit_code == 0:
            return True
        # CLI failed; fall back to static paths if available
        if provider_config.provider_root:
            logger.warning(
                'provider_cli_failed_falling_back',
                alias=alias,
                cli=provider_config.cli,
                reason='CLI link failed; using provider_root as fallback',
            )
            return _register_static(alias, provider_config, config_dir) is not None
        return False

    return _register_static(alias, provider_config, config_dir) is not None


def _check_or_register(
    alias: str,
    provider_config: ProviderConfig,
    config_dir: Path,
    *,
    force: bool,
) -> bool:
    """Return True if the provider is ready (valid info on disk or freshly registered)."""
    if not force:
        info = load_provider_info(alias, config_dir)
        if info is not None:
            if _paths_valid(info):
                logger.debug('provider_already_ready', alias=alias)
                return True
            logger.warning(
                'provider_info_stale',
                alias=alias,
                resources_dir=info.resources_dir,
                provider_root=info.provider_root or '(same as resources_dir)',
                reason='recorded paths no longer exist; re-registering',
            )
    return _register_provider(alias, provider_config, config_dir)


def ensure_providers_ready(
    aliases: list[str],
    providers: dict[str, ProviderConfig],
    config_dir: Path,
    *,
    force: bool = False,
    strict: bool = False,
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

    Args:
        aliases: Provider aliases to process, in the desired order.
        providers: Raw :class:`ProviderConfig` map from the config file.
        config_dir: Directory containing ``repolish.yaml``.
        force: Re-register even when an existing info file is valid.
            Used by ``repolish link`` to always refresh registrations.
        strict: Raise :exc:`~repolish.exceptions.ProviderNotReadyError`
            when any provider could not be registered.  Use for CI.

    Returns:
        :class:`ProviderReadinessResult` with ``ready`` and ``failed`` lists.

    Raises:
        ProviderNotReadyError: When *strict* is True and any provider failed.
    """
    result = ProviderReadinessResult()

    for alias in aliases:
        if alias not in providers:
            logger.warning('provider_not_in_config', alias=alias)
            continue

        if _check_or_register(alias, providers[alias], config_dir, force=force):
            result.ready.append(alias)
        else:
            logger.warning(
                'provider_not_ready',
                alias=alias,
                suggestion='run `repolish link` or verify provider_root in repolish.yaml',
            )
            result.failed.append(alias)

    if strict and result.failed:
        msg = f'providers not ready: {", ".join(result.failed)}'
        raise ProviderNotReadyError(msg)

    return result
