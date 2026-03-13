import json
from importlib.metadata import packages_distributions
from importlib.util import find_spec
from pathlib import Path, PurePosixPath
from typing import cast

from hotlog import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)


def _source_path_from_dist(dist: object) -> Path | None:  # pragma: no cover
    """Return the resolved ``file://`` source path from ``direct_url.json``, or ``None``."""
    read = getattr(dist, 'read_text', lambda _: None)
    raw = read('direct_url.json')
    if not raw:
        return None
    url = json.loads(raw).get('url', '')
    return Path(url[7:]).resolve() if url.startswith('file://') else None


def _project_name_from_direct_url(pkg: str) -> str:  # pragma: no cover
    """Resolve distribution name for an editable install via ``direct_url.json``.

    ``packages_distributions()`` often omits packages installed with
    ``pip install -e .``.  As a fallback we iterate all known distributions,
    find any whose ``direct_url.json`` points at a source directory that
    contains the package, and return that distribution's metadata name.
    Returns an empty string when no matching distribution is found.
    """
    from importlib.metadata import distributions  # noqa: PLC0415

    spec = find_spec(pkg)
    if not spec or not spec.submodule_search_locations:
        return ''
    pkg_path = Path(next(iter(spec.submodule_search_locations))).resolve()
    for dist in distributions():
        try:
            source = _source_path_from_dist(dist)
            if source and pkg_path.is_relative_to(source):
                return getattr(dist, 'name', '') or ''
        except Exception:  # noqa: BLE001, S110 - best-effort scan
            pass
    return ''


def resolve_package_names(package_attr: str | None) -> tuple[str, str]:
    """Return ``(package_name, project_name)`` for a ``__package__`` attribute value.

    ``package_name`` is the top-level Python import name (e.g. ``codeguide_workspace``).
    ``project_name`` is the distribution name from ``pyproject.toml [project] name``
    resolved first via :func:`importlib.metadata.packages_distributions`, then
    via :func:`_project_name_from_direct_url` as a fallback for editable installs
    (e.g. ``codeguide-workspace``).  Returns a pair of empty strings when
    ``package_attr`` is ``None``/empty.  Metadata lookup failures are logged
    at ``DEBUG`` level and cause ``project_name`` to be returned as ``''``.
    """
    pkg = (package_attr or '').split('.')[0]
    if not pkg:
        return '', ''
    project = ''
    try:
        dists = packages_distributions().get(pkg, [])
        if dists:
            project = dists[0]
    except Exception as exc:  # noqa: BLE001 - metadata lookup is best-effort
        logger.debug(
            'package_distributions_lookup_failed',
            package=pkg,
            error=str(exc),
        )
    if not project:
        project = _project_name_from_direct_url(pkg)
    return pkg, project


def ctx_to_dict(ctx: object | None) -> dict[str, object]:
    """Normalize a provider-style context object to a plain dict.

    The value may be a :class:`pydantic.BaseModel` (in which case `model_dump`
    is called) or already a `dict`.  `None` or any other type becomes an
    empty dictionary to avoid leaking unexpected values into rendered
    templates or logs.  This helper is used by both the loader and command
    layers and lives here to avoid duplication.
    """
    if isinstance(ctx, BaseModel):
        return ctx.model_dump()
    if isinstance(ctx, dict):
        return cast('dict[str, object]', ctx)
    return {}


def ctx_keys(ctx_obj: object | None) -> list[str]:
    """Return the keys of a provider-style context object.

    Behaves similarly to :func:`ctx_to_dict` but only returns the top-level
    keys rather than the full mapping.  `BaseModel` instances are converted
    to dicts via `model_dump`.  `None` or unsupported types yield an
    empty list.  This helper is handy when iterating or filtering context
    values without materializing a full dictionary.
    """
    if isinstance(ctx_obj, BaseModel):
        return cast('list[str]', list(ctx_obj.model_dump().keys()))
    if isinstance(ctx_obj, dict):
        return cast('list[str]', list(ctx_obj.keys()))
    return []


def is_conditional_file(path_str: str) -> bool:
    """Check if a file's name starts with the _repolish. prefix.

    This prefix is used both for conditional template files and for
    temporary mapping outputs written during hydration.  By treating any
    filename beginning with `_repolish.` as special we automatically skip
    such files during regular rendering and application steps, and they are
    easy to spot when inspecting the staging directory.

    Args:
        path_str: POSIX-style relative path

    Returns:
        True if the filename starts with '_repolish.'
    """
    filename = PurePosixPath(path_str).name
    return filename.startswith('_repolish.')
