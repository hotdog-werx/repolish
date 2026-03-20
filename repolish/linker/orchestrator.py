"""High-level provider processing orchestration."""

import importlib.util
import subprocess
from inspect import isclass
from pathlib import Path

from hotlog import get_logger

from repolish.config import ProviderConfig
from repolish.config.models.provider import (
    ProviderSymlink,
    ResolvedProviderInfo,
)
from repolish.linker.providers import run_provider_link, save_provider_info
from repolish.linker.symlinks import create_additional_link
from repolish.providers.models import Provider, Symlink

logger = get_logger(__name__)


def create_provider_symlinks(
    provider_name: str,
    resources_dir: Path,
    symlinks: list[ProviderSymlink],
) -> None:
    """Create symlinks for a provider from its resources into the project root.

    Args:
        provider_name: Alias of the provider.
        resources_dir: Absolute path to the provider's resource directory.
        symlinks: List of symlink configurations to materialise.
    """
    if not symlinks:
        return

    logger.info(
        'creating_provider_symlinks',
        provider=provider_name,
        count=len(symlinks),
        _display_level=1,
    )

    for symlink in symlinks:
        logger.debug(
            'creating_symlink',
            source=str(symlink.source),
            target=str(symlink.target),
        )
        create_additional_link(
            resources_dir=resources_dir,
            provider_name=provider_name,
            source=str(symlink.source),
            target=str(symlink.target),
            force=True,
        )

    logger.info(
        'symlinks_created',
        provider=provider_name,
        count=len(symlinks),
        _display_level=1,
    )


def _symlinks_from_module(mod: object) -> list[ProviderSymlink]:
    """Return default symlinks declared by the ``Provider`` subclass in *mod*."""
    for val in vars(mod).values():
        if isclass(val) and issubclass(val, Provider) and val is not Provider:
            symlinks: list[Symlink] = val().create_default_symlinks()
            return [ProviderSymlink(source=Path(s.source), target=Path(s.target)) for s in symlinks]
    return []  # pragma: no cover - defensive fallback, we make sure that a provider is declared in repolish.py


def _load_provider_default_symlinks(
    provider_root: Path,
) -> list[ProviderSymlink]:
    """Import ``repolish.py`` from *provider_root* and return its default symlinks.

    Finds the ``Provider`` subclass instance in the module and calls
    :meth:`~repolish.providers.models.Provider.create_default_symlinks`.
    Returns an empty list when the file is absent, has no Provider instance,
    or raises an exception during loading.
    """
    repolish_py = provider_root / 'repolish.py'
    if not repolish_py.exists():
        return []
    try:
        spec = importlib.util.spec_from_file_location(
            '_repolish_tmp_symlinks',
            repolish_py,
        )
        if spec is None or spec.loader is None:  # pragma: no cover
            return []
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return _symlinks_from_module(mod)
    except Exception:  # noqa: BLE001 # pragma: no cover - defence against broken repolish.py in a provider; hard to induce cleanly in tests
        logger.warning(
            'provider_default_symlinks_load_failed',
            provider_root=str(provider_root),
        )
    return []  # pragma: no cover


def collect_provider_symlinks(
    providers: dict[str, ResolvedProviderInfo],
    providers_config: dict[str, ProviderConfig],
) -> dict[str, list[ProviderSymlink]]:
    """Resolve the effective symlink list per provider without creating them.

    Explicit entries in ``repolish.yaml`` take priority; absent entries fall
    back to the defaults declared in ``repolish.py``.  SessionBundle with no
    effective symlinks are omitted from the result.

    Args:
        providers: Resolved provider map from :func:`~repolish.config.load_config`.
        providers_config: Raw provider config map from the YAML (carries the
            ``symlinks`` override field).
    """
    result: dict[str, list[ProviderSymlink]] = {}
    for alias, info in providers.items():
        raw = providers_config.get(alias)
        if raw is not None and raw.symlinks is not None:
            # Explicit override (may be empty list to suppress all symlinks).
            effective: list[ProviderSymlink] = list(raw.symlinks)
        else:
            effective = _load_provider_default_symlinks(info.provider_root)
        if effective:
            result[alias] = effective
    return result


def process_provider(
    provider_name: str,
    provider_config: ProviderConfig,
    config_dir: Path,
) -> int:
    """Run the provider's link CLI to materialise resources under ``.repolish/``.

    This function's sole responsibility is invoking the CLI that symlinks (or
    copies) the provider's package resources into ``.repolish/<alias>/``.
    Symlink management is handled separately by :func:`create_provider_symlinks`.

    Args:
        provider_name: Alias of the provider.
        provider_config: Provider configuration from ``repolish.yaml``.
        config_dir: Directory containing ``repolish.yaml``.

    Returns:
        0 on success, 1 on failure.
    """
    if not provider_config.cli:
        logger.info(
            'skipping_provider_no_cli',
            provider=provider_name,
            _display_level=1,
        )
        return 0

    try:
        provider_info = run_provider_link(provider_name, provider_config.cli)
    except subprocess.CalledProcessError as e:
        logger.exception(
            'provider_link_failed',
            provider=provider_name,
            error=str(e),
        )
        return 1
    except FileNotFoundError:
        logger.exception(
            'provider_cli_not_found',
            provider=provider_name,
            command=provider_config.cli,
        )
        return 1

    save_provider_info(provider_name, provider_info, config_dir)
    return 0
