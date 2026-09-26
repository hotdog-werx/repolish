"""In-process registration for module-declared providers.

A provider configured with ``module:`` names an installed Python module
instead of a linker CLI. Both registration halves the CLI used to pay a
subprocess for happen here, in the main repolish process:

- the probe (:func:`probe_module_info`) locates the package with
  :func:`importlib.util.find_spec` and computes the same
  :class:`~repolish.config.models.metadata.ProviderFileInfo` the CLI's
  ``--info`` flag prints, without executing any module code;
- the link (:func:`run_module_link`) calls
  :func:`~repolish.linker.symlinks.link_resources`, the exact function the
  generated CLI wraps, and returns the info for
  :func:`~repolish.linker.providers.save_provider_info` to persist.

The staleness protocol is unchanged: :func:`run_module_link` produces info
that :func:`~repolish.linker.providers.locations_match` and
:func:`~repolish.linker.providers.link_target_current` compare against the
cached ``provider-info.<alias>.json``, so a module provider that moved (dev
and release switch) re-links exactly like a CLI provider that moved.
"""

from importlib.util import find_spec
from pathlib import Path

from hotlog import get_logger

from repolish.config.models.metadata import ProviderFileInfo
from repolish.config.models.provider import ModuleProviderConfig
from repolish.exceptions import ModuleLinkError
from repolish.linker.symlinks import link_resources
from repolish.pkginfo import resolve_package_identity

logger = get_logger(__name__)


def _package_root(name: str) -> Path:
    """Return the installed package directory for *name*.

    Uses :func:`importlib.util.find_spec`, which resolves regular and
    namespace packages as well as editable installs to their real location.

    Args:
        name: Dotted module name declared in the provider config.

    Returns:
        Resolved path of the package directory.

    Raises:
        ModuleLinkError: If the module is not importable from the current
            environment, or it resolves to something without a package
            directory (e.g. a plain module or a namespace root).
    """
    try:
        spec = find_spec(name)
    except (ModuleNotFoundError, ValueError) as exc:
        msg = f'Provider module {name!r} is not importable: {exc}'
        raise ModuleLinkError(msg) from exc
    if spec is None or not spec.submodule_search_locations:
        msg = (
            f'Provider module {name!r} does not resolve to a package '
            'directory; module: must name the provider package itself'
        )
        raise ModuleLinkError(msg)
    return Path(next(iter(spec.submodule_search_locations))).resolve()


def probe_module_info(
    module: ModuleProviderConfig,
    config_dir: Path,
) -> ProviderFileInfo:
    """Compute the provider info for *module* without linking anything.

    The in-process equivalent of running ``<cli> --info``: locates the
    package, resolves its identity, and reports where its resources will be
    linked under ``<config_dir>/.repolish/``. No module code is executed.

    Args:
        module: Module declaration from ``repolish.yaml``.
        config_dir: Directory containing ``repolish.yaml``; the resources
            target lives under its ``.repolish/`` subdirectory.

    Returns:
        Provider info with the linked target paths and package location.

    Raises:
        ModuleLinkError: If the module cannot be located as a package.
    """
    pkg_root = _package_root(module.name)
    pkg_name, project_name = resolve_package_identity(module.name)
    library_name = project_name or pkg_name.replace('_', '-')
    resources_dir = config_dir / '.repolish' / library_name
    logger.debug(
        'module_provider_probed',
        module=module.name,
        library_name=library_name,
        resources_dir=str(resources_dir),
    )
    return ProviderFileInfo(
        resources_dir=str(resources_dir),
        provider_root=str(resources_dir / module.provider_root),
        site_package_dir=str(pkg_root / module.resources_dir),
        package_name=pkg_name,
        project_name=project_name,
    )


def run_module_link(
    provider_name: str,
    module: ModuleProviderConfig,
    config_dir: Path,
    *,
    fresh_info: ProviderFileInfo | None = None,
) -> ProviderFileInfo:
    """Link a module-declared provider's resources in-process.

    Mirrors :func:`~repolish.linker.providers.run_provider_link` for the
    module path: probes the module's location (or reuses an already-run
    probe passed as *fresh_info*), then links the packaged resources into
    ``.repolish/<library-name>/`` with
    :func:`~repolish.linker.symlinks.link_resources`.

    Args:
        provider_name: Alias of the provider.
        module: Module declaration from ``repolish.yaml``.
        config_dir: Directory containing ``repolish.yaml``.
        fresh_info: Info from an already-run probe, when the caller probed
            before deciding to register; avoids recomputing the location.

    Returns:
        Provider information for :func:`~repolish.linker.providers.save_provider_info`.

    Raises:
        ModuleLinkError: If the module cannot be located as a package.
        FileNotFoundError: If the package's resources directory is missing.
    """
    logger.info(
        'running_module_link',
        provider=provider_name,
        module=module.name,
        _display_level=1,
    )
    provider_info = fresh_info if fresh_info is not None else probe_module_info(module, config_dir)
    link_resources(
        source_dir=Path(provider_info.site_package_dir),
        target_dir=Path(provider_info.resources_dir),
    )
    logger.info(
        'provider_linked',
        provider=provider_name,
        target=str(provider_info.resources_dir),
        _display_level=1,
    )
    return provider_info
