"""Resolve Python package identity: module name and distribution name.

Works correctly for both regular packages and namespace packages:

- Regular package: ``devkit_zensical/__init__.py`` exists.
  ``__package__ = 'devkit_zensical'`` → ``module_name = 'devkit_zensical'``

- Namespace package: ``devkit/__init__.py`` is absent; only
  ``devkit/zensical/__init__.py`` exists.
  ``__package__ = 'devkit.zensical'`` → ``module_name = 'devkit.zensical'``

The detection key is ``importlib.util.find_spec(top_level).origin``:
a namespace package has ``origin = None`` because it has no ``__init__.py``.
"""

import json
from importlib.machinery import ModuleSpec
from importlib.metadata import (
    Distribution,
    distributions,
    packages_distributions,
)
from importlib.util import find_spec
from pathlib import Path

from hotlog import get_logger

logger = get_logger(__name__)


def resolve_package_identity(package_attr: str | None) -> tuple[str, str]:
    """Return ``(module_name, project_name)`` for a ``__package__`` value.

    ``module_name`` is the canonical importable dotted name:

    - Regular flat package: ``'devkit_zensical'``
    - Namespace package:    ``'devkit.zensical'``

    ``project_name`` is the distribution name from package metadata
    (e.g. ``'devkit-zensical'``).

    Resolution order for ``project_name``:

    1. :func:`importlib.metadata.packages_distributions` — covers
       most installed packages.
    2. :func:`_project_from_direct_url` — fallback for editable installs
       that are absent from ``packages_distributions()``.

    Returns ``('', '')`` when ``package_attr`` is ``None`` or empty.
    """
    if not package_attr:
        return '', ''

    top_level = package_attr.split('.')[0]
    module_name = _resolve_module_name(package_attr)

    if module_name != top_level:
        # Namespace sub-package: packages_distributions() only knows the shared
        # top-level key (e.g. 'devkit') and may return the wrong distribution
        # when multiple sub-packages share a namespace.  Use RECORD scanning.
        project_name = _project_from_distribution_files(module_name)
        if not project_name:
            project_name = _project_from_direct_url(module_name)
        if not project_name:
            # Last resort: if only one distribution claims this namespace
            # top-level, it must be the right one (ambiguity only arises with
            # multiple sub-packages sharing a namespace, e.g. devkit-python +
            # devkit-workspace both under 'devkit').
            candidates = _project_from_distributions_list(top_level)
            if len(candidates) == 1:
                project_name = candidates[0]
    else:
        project_name = _project_from_distributions(top_level)
        if not project_name:
            project_name = _project_from_direct_url(module_name)

    return module_name, project_name


def _resolve_module_name(package_attr: str) -> str:
    """Derive the canonical module name, handling namespace packages.

    For a flat package, the top-level component is the module name.
    For a namespace package (top-level has no ``__init__.py``), this walks
    down the dotted path until it finds the first component that owns an
    ``__init__.py``, returning that prefix as the canonical name.

    Examples::

        _resolve_module_name('devkit_zensical')          -> 'devkit_zensical'
        _resolve_module_name('devkit.zensical')          -> 'devkit.zensical'
        _resolve_module_name('devkit.zensical.repolish') -> 'devkit.zensical'
    """
    parts = package_attr.split('.')
    top_level = parts[0]

    if not _is_namespace_top_level(top_level):
        return top_level

    # Namespace root found: walk down until we reach the first level
    # that has an __init__.py (the real package, not the namespace container).
    for depth in range(2, len(parts) + 1):
        candidate = '.'.join(parts[:depth])
        spec = _safe_find_spec(candidate)
        if spec is not None and spec.origin is not None:
            return candidate

    # All levels are namespaces or unresolvable: return as-is.
    return package_attr


def _is_namespace_top_level(top_level: str) -> bool:
    """Return ``True`` when *top_level* is a namespace package.

    A namespace package has no ``__init__.py``, which manifests as
    ``spec.origin is None`` from :func:`importlib.util.find_spec`.
    """
    spec = _safe_find_spec(top_level)
    return spec is not None and spec.origin is None


def _safe_find_spec(name: str) -> ModuleSpec | None:
    """Return the module spec for *name*, or ``None`` on any error."""
    try:
        return find_spec(name)
    except (ModuleNotFoundError, ValueError):
        return None


def _project_from_distributions(top_level: str) -> str:
    """Look up the distribution name for *top_level* via importlib.metadata.

    Returns the first distribution name found, or ``''`` if none.
    """
    candidates = _project_from_distributions_list(top_level)
    return candidates[0] if candidates else ''


def _project_from_distributions_list(top_level: str) -> list[str]:
    """Return all distribution names associated with *top_level*."""
    try:
        return packages_distributions().get(top_level, [])
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            'packages_distributions_failed',
            top_level=top_level,
            error=str(exc),
        )
        return []


def _project_from_distribution_files(module_name: str) -> str:
    """Return the distribution name that owns *module_name* by scanning RECORD files.

    For namespace sub-packages such as ``devkit.python``, the top-level
    ``packages_distributions()`` lookup only returns the shared namespace root
    (``'devkit'``) and cannot distinguish between ``devkit-python`` and
    ``devkit-workspace``.  This function finds the distribution whose installed
    files include a path under the module's actual directory.

    Returns ``''`` when no matching distribution is found.
    """
    spec = _safe_find_spec(module_name)
    if spec is None or not spec.submodule_search_locations:
        return ''

    pkg_path = Path(next(iter(spec.submodule_search_locations))).resolve()

    for dist in distributions():
        try:
            files = dist.files
            if files is None:
                continue
            for f in files:
                if pkg_path in Path(str(dist.locate_file(f))).resolve().parents:
                    return dist.metadata['Name'] or ''
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'package_match_error',
                error=str(exc),
                dist=str(dist.metadata),
            )

    return ''


def _project_from_direct_url(module_name: str) -> str:
    """Fallback resolver for editable installs missing from packages_distributions.

    Scans all known distributions for a ``direct_url.json`` whose source
    directory contains the package's import location, then returns that
    distribution's ``Name`` metadata.  Returns ``''`` when no match is
    found.

    This handles packages installed with ``pip install -e .`` (or ``uv pip
    install -e .``) where the package may not appear in the output of
    :func:`importlib.metadata.packages_distributions`.
    """
    # For namespace packages use the full dotted name to get the right
    # submodule_search_locations; for flat packages top_level == module_name.
    pkg_spec = _safe_find_spec(module_name)
    if pkg_spec is None or not pkg_spec.submodule_search_locations:
        return ''

    pkg_path = Path(next(iter(pkg_spec.submodule_search_locations))).resolve()

    # Collect all matching distributions and pick the most specific one
    # (longest source path).  A broad workspace root (e.g. the repolish repo)
    # would otherwise shadow a nested provider installed from a sub-directory.
    best_name = ''
    best_len = -1
    for dist in distributions():
        source = _source_path_from_dist(dist)
        if source and pkg_path.is_relative_to(source):
            src_len = len(source.parts)
            if src_len > best_len:
                best_len = src_len
                best_name = dist.metadata['Name'] or ''

    return best_name


def _source_path_from_dist(dist: Distribution) -> Path | None:
    """Return the resolved source path from ``direct_url.json``, or ``None``."""
    raw = dist.read_text('direct_url.json')
    if not raw:
        return None
    url = json.loads(raw).get('url', '')
    return Path(url[7:]).resolve() if url.startswith('file://') else None
