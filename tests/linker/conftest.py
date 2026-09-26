"""Shared fixtures for registration-engine tests."""

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def module_pkg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """An importable package with the default resources layout.

    The package is a plain directory on sys.path (not an installed
    distribution), so resolve_package_identity finds no project name and
    the library name falls back to the module name with dashes: mylib-ws.
    """
    pkg_parent = tmp_path / 'pkgroot'
    pkg_root = pkg_parent / 'mylib_ws'
    pkg_root.mkdir(parents=True)
    (pkg_root / '__init__.py').write_text('')
    resources = pkg_root / 'resources'
    templates = resources / 'templates'
    templates.mkdir(parents=True)
    (templates / 'repolish.py').write_text('')
    (resources / 'file.txt').write_text('content')
    monkeypatch.syspath_prepend(str(pkg_parent))
    return {'pkg_root': pkg_root, 'resources': resources}
