"""Session-scoped fixtures that install test providers into the live test venv.

Flow
----
1. Build a wheel for each fixture provider (``uv build``).
2. Install the wheel into the same Python that is running pytest
   (``uv pip install --python <sys.executable> --no-deps``).
   ``--no-deps`` is intentional: ``repolish`` is already present in the
   test environment and is not on PyPI, so dependency resolution would fail.
3. Yield an ``InstalledProviders`` object that carries the paths tests need.
4. Uninstall the packages and delete the temporary dist directory on teardown.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

_EXAMPLES_DIR = Path(__file__).parent.parent.parent / 'provider-examples'
_SIMPLE_PROVIDER_DIR = _EXAMPLES_DIR / 'simple-provider'
_SCAFFOLD_PROVIDER_DIR = _EXAMPLES_DIR / 'scaffold-provider'
_DIST_DIR = _EXAMPLES_DIR / '.dist'


@dataclass
class InstalledProviders:
    """Paths to providers installed for the test session."""

    # directory containing the console-script executables for this Python
    venv_bin: Path
    # absolute path to simple_provider's templates directory (holds repolish.py)
    simple_provider_root: Path
    # absolute path to scaffold_provider's templates directory (holds repolish.py)
    scaffold_provider_root: Path


def _build_wheel(source_dir: Path, out_dir: Path, package_name: str) -> Path:
    """Build a wheel and return the path to the produced .whl file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603
        ['uv', 'build', '--wheel', '--out-dir', str(out_dir)],  # noqa: S607
        cwd=str(source_dir),
        check=True,
    )
    wheels = sorted(out_dir.glob(f'{package_name}-*.whl'))
    assert wheels, f'uv build produced no wheel matching {package_name}-*.whl in {out_dir}'
    return wheels[-1]


def _install_wheel(wheel: Path) -> None:
    """Install a wheel into the running Python, skipping its dependencies."""
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            'uv',
            'pip',
            'install',
            '--python',
            sys.executable,
            '--no-deps',
            str(wheel),
        ],
        check=True,
    )


def _uninstall_package(dist_name: str) -> None:
    """Uninstall a distribution from the running Python."""
    subprocess.run(  # noqa: S603
        ['uv', 'pip', 'uninstall', '--python', sys.executable, dist_name],  # noqa: S607
        check=True,
    )


def _pkg_sub_path(package_name: str, sub: str) -> Path:
    """Return ``<installed_package_root>/<sub>`` for an installed package."""
    importlib.invalidate_caches()
    spec = importlib.util.find_spec(package_name)
    assert spec
    assert spec.submodule_search_locations, (
        f"'{package_name}' not importable after install - check that the wheel "
        'was installed into the correct Python environment.'
    )
    pkg_root = Path(next(iter(spec.submodule_search_locations))).resolve()
    return pkg_root / sub


@pytest.fixture(scope='session', autouse=True)
def installed_providers() -> Generator[InstalledProviders, None, None]:
    """Build, install, and expose test providers; uninstall on teardown."""
    simple_wheel = _build_wheel(
        _SIMPLE_PROVIDER_DIR,
        _DIST_DIR,
        'simple_provider',
    )
    _install_wheel(simple_wheel)
    scaffold_wheel = _build_wheel(
        _SCAFFOLD_PROVIDER_DIR,
        _DIST_DIR,
        'scaffold_provider',
    )
    _install_wheel(scaffold_wheel)

    simple_root = _pkg_sub_path('simple_provider', 'resources/templates')
    scaffold_root = _pkg_sub_path('scaffold_provider', 'resources/templates')

    yield InstalledProviders(
        venv_bin=Path(sys.executable).parent,
        simple_provider_root=simple_root,
        scaffold_provider_root=scaffold_root,
    )

    _uninstall_package('simple-provider')
    _uninstall_package('scaffold-provider')
    shutil.rmtree(_DIST_DIR, ignore_errors=True)
