"""High-level provider processing orchestration."""

import importlib.util
import subprocess
from inspect import isclass
from pathlib import Path
from typing import cast

from hotlog import get_logger

from repolish.config import ProviderConfig
from repolish.config.models.provider import (
    ProviderSymlink,
    ResolvedProviderInfo,
)
from repolish.linker.providers import run_provider_link, save_provider_info
from repolish.linker.symlinks import create_additional_link
from repolish.providers.models import ModeHandler, Provider, Symlink

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


def _mode_handler_cls(
    inst: Provider,  # type: ignore[type-arg]
    mode: str,
) -> type[ModeHandler] | None:  # type: ignore[type-arg]
    """Return the mode handler class registered on *inst* for *mode*."""
    if mode == 'root':
        return inst.root_mode
    if mode == 'member':
        return inst.member_mode
    return inst.standalone_mode


def _symlinks_from_module(
    mod: object,
    mode: str,
    provider_root: Path,
) -> list[ProviderSymlink]:
    """Return default symlinks for *mode* declared by the ``Provider`` (and its handler) in *mod*.

    Provider-level symlinks are shared across all modes; handler-level symlinks
    are mode-specific additions.  Both are combined and returned together.
    """
    for val in vars(mod).values():
        if isclass(val) and issubclass(val, Provider) and val is not Provider:
            inst = val()
            inst.templates_root = provider_root
            # Global symlinks defined on the Provider itself (all modes).
            all_symlinks: list[Symlink] = list(
                cast('list[Symlink]', inst.create_default_symlinks()),
            )
            # Mode-specific symlinks from the registered handler.
            handler_cls = _mode_handler_cls(inst, mode)
            if handler_cls is not None:
                handler = handler_cls()
                handler.templates_root = provider_root / mode
                all_symlinks += handler.create_default_symlinks()
            return [ProviderSymlink(source=Path(s.source), target=Path(s.target)) for s in all_symlinks]
    return []  # pragma: no cover - defensive fallback, we make sure that a provider is declared in repolish.py


def _load_provider_default_symlinks(
    provider_root: Path,
    mode: str,
) -> list[ProviderSymlink]:
    """Import ``repolish.py`` from *provider_root* and return its default symlinks for *mode*.

    Finds the ``Provider`` subclass and calls ``create_default_symlinks`` on both
    the provider and its registered mode handler (if any).  Returns an empty list
    when the file is absent, has no Provider subclass, or raises during loading.
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
        return _symlinks_from_module(mod, mode, provider_root)
    except Exception:  # noqa: BLE001 # pragma: no cover - defence against broken repolish.py in a provider; hard to induce cleanly in tests
        logger.warning(
            'provider_default_symlinks_load_failed',
            provider_root=str(provider_root),
        )
    return []  # pragma: no cover


def collect_provider_symlinks(
    providers: dict[str, ResolvedProviderInfo],
    providers_config: dict[str, ProviderConfig],
    mode: str = 'standalone',
) -> dict[str, list[ProviderSymlink]]:
    """Resolve the effective symlink list per provider without creating them.

    Explicit entries in ``repolish.yaml`` take priority; absent entries fall
    back to the defaults declared in ``repolish.py`` (both provider-level and
    mode-handler-level).  Providers with no effective symlinks are omitted.

    Args:
        providers: Resolved provider map from :func:`~repolish.config.load_config`.
        providers_config: Raw provider config map from the YAML (carries the
            ``symlinks`` override field).
        mode: Workspace mode (``'root'``, ``'member'``, or ``'standalone'``)
            used to select the correct :class:`~repolish.providers.models.ModeHandler`.
    """
    result: dict[str, list[ProviderSymlink]] = {}
    for alias, info in providers.items():
        raw = providers_config.get(alias)
        if raw is not None and raw.symlinks is not None:
            # Explicit override (may be empty list to suppress all symlinks).
            effective: list[ProviderSymlink] = list(raw.symlinks)
        else:
            effective = _load_provider_default_symlinks(
                info.provider_root,
                mode,
            )
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
