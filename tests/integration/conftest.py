"""Session-scoped fixtures that install test providers into the live test venv.

Providers are built and installed once by pytest_configure_node() in the
root conftest before any workers start. This module just provides the
fixture that returns provider info for test use.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from repolish.cli.main import app
from repolish.cli.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Generator

    from repolish.cli.testing import Result

_EXAMPLES_DIR = Path(__file__).parent.parent.parent / 'provider-examples'
_DIST_DIR = _EXAMPLES_DIR / '.dist'

_FIXTURES_DIR = Path(__file__).parent / 'fixtures'


def init_git_repo(
    path: Path,
    *,
    owner: str = 'test-owner',
    repo: str = 'test-repo',
) -> None:
    """Initialise a bare-minimum git repo so git-dependent provider code doesn't fail.

    Sets up ``origin`` with a GitHub HTTPS URL so ``get_owner_repo()`` can
    parse the owner and repo name.  Uses ``--initial-branch=main`` to avoid
    stderr noise about the default branch name changing across git versions;
    falls back silently for older git that doesn't know the flag.
    """

    def _run(*args: str) -> None:
        subprocess.run(  # noqa: S603 - args are hardcoded by the fixture, no user input
            list(args),
            cwd=str(path),
            check=True,
            capture_output=True,
        )

    try:
        _run('git', 'init', '--initial-branch=main')
    except subprocess.CalledProcessError:
        _run('git', 'init')  # older git without --initial-branch
    _run('git', 'config', 'user.email', 'test@example.com')
    _run('git', 'config', 'user.name', 'Test User')
    _run(
        'git',
        'remote',
        'add',
        'origin',
        f'https://github.com/{owner}/{repo}.git',
    )


@dataclass(frozen=True)
class FixtureRepo:
    """A single fixture repository directory.

    Call ``stage(tmp_path)`` to copy the fixture into a temporary directory
    and get back the destination path ready for use in a test.
    """

    path: Path

    def stage(
        self,
        tmp_path: Path,
        *,
        owner: str = 'test-owner',
        repo: str = 'test-repo',
    ) -> Path:
        """Copy the fixture into ``tmp_path``, init a git repo, and return the path."""
        dest = shutil.copytree(self.path, tmp_path / self.path.name)
        init_git_repo(dest, owner=owner, repo=repo)
        return dest


@dataclass(frozen=True)
class Fixtures:
    """Paths to all fixture repos used by integration tests.

    Add a new field here whenever a new fixture directory is created under
    ``tests/integration/fixtures/``.  Tests should import the module-level
    ``fixtures`` singleton rather than constructing their own paths.
    """

    simple_repo: FixtureRepo
    scaffold_fresh: FixtureRepo
    scaffold_existing_init: FixtureRepo
    scaffold_notice_fresh: FixtureRepo
    file_mappings_variant_a_fresh: FixtureRepo
    file_mappings_variant_b_fresh: FixtureRepo
    file_mappings_nested_ci_fresh: FixtureRepo
    file_mappings_variant_a_existing: FixtureRepo
    monorepo_basic: FixtureRepo
    monorepo_devkit: FixtureRepo

    @classmethod
    def from_dir(cls, base: Path) -> Fixtures:
        """Build a Fixtures instance from the fixtures root directory."""
        return cls(
            simple_repo=FixtureRepo(base / 'simple-repo'),
            scaffold_fresh=FixtureRepo(base / 'scaffold-fresh'),
            scaffold_existing_init=FixtureRepo(base / 'scaffold-existing-init'),
            scaffold_notice_fresh=FixtureRepo(base / 'scaffold-notice-fresh'),
            file_mappings_variant_a_fresh=FixtureRepo(
                base / 'file-mappings-variant-a-fresh',
            ),
            file_mappings_variant_b_fresh=FixtureRepo(
                base / 'file-mappings-variant-b-fresh',
            ),
            file_mappings_nested_ci_fresh=FixtureRepo(
                base / 'file-mappings-nested-ci-fresh',
            ),
            file_mappings_variant_a_existing=FixtureRepo(
                base / 'file-mappings-variant-a-existing',
            ),
            monorepo_basic=FixtureRepo(base / 'monorepo-basic'),
            monorepo_devkit=FixtureRepo(base / 'monorepo-devkit'),
        )


fixtures = Fixtures.from_dir(_FIXTURES_DIR)

_runner = CliRunner()


def run_repolish(args: list[str], *, exit_code: int = 0) -> Result:
    """Invoke the repolish CLI, assert the exit code, and return the result.

    Use this helper for both success and failure-based tests.

    Typical workflow:

    - When a command is expected to succeed, inspect ``result.output`` and make
      assertions against the user-visible text. This is the normal path for
      behaviour-based integration tests.
    - When a command is expected to fail, pass ``exit_code=1`` (or the expected
      non-zero code) and inspect ``result.exception``. Print the traceback with
      ``traceback.print_exception(result.exception)`` to reveal the underlying
      crash or error, and inspect ``result.output`` to see which user-facing
      message was emitted.

    Example::

        result = run_repolish(['apply'], exit_code=1)
        import traceback
        traceback.print_exception(result.exception)
        assert 'some expected message' in result.output

    This keeps the test focused on the public contract while still making it
    easy to distinguish a real repolish bug from a bad assertion.
    """
    result = _runner.invoke(app, args)
    if exit_code != -1:  # escape-hatch for debugging with --exit-code=-1 to skip the assertion
        assert result.exit_code == exit_code, (
            f'expected exit_code={exit_code}, got {result.exit_code}\n{result.output}'
        )
    return result


@dataclass(frozen=True)
class ProviderSpec:
    """Metadata extracted from a provider's pyproject.toml."""

    # directory that contains pyproject.toml (used as cwd for uv build)
    source_dir: Path
    # distribution name as declared in [project].name (e.g. 'simple-provider')
    dist_name: str
    # dotted importable package name; read from [tool.uv.build-backend] module-name
    # when present, otherwise derived from dist_name (e.g. 'simple_provider', 'devkit.python')
    import_path: str


@dataclass(frozen=True)
class InstalledProvider:
    """A single provider discovered from provider-examples/ and installed for the session."""

    # absolute path to <package>/resources/templates (holds repolish.py)
    root: Path


@dataclass(frozen=True)
class InstalledProviders:
    """All providers auto-discovered from provider-examples/ and installed for the session.

    Access individual providers by their folder name (kebab-case):

        installed_providers.providers['simple-provider'].root
    """

    # directory containing the console-script executables for this Python
    venv_bin: Path
    # keyed by provider folder name (= dist name, e.g. 'simple-provider')
    providers: dict[str, InstalledProvider]


def _build_wheel(source_dir: Path, out_dir: Path, package_name: str) -> Path:
    """Build a wheel and return the path to the produced .whl file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - hardcoded build args, no user input
        ['uv', 'build', '--wheel', '--out-dir', str(out_dir)],  # noqa: S607 - uv is a known tool resolved from PATH
        cwd=str(source_dir),
        check=True,
    )
    wheels = sorted(out_dir.glob(f'{package_name}-*.whl'))
    assert wheels, f'uv build produced no wheel matching {package_name}-*.whl in {out_dir}'
    return wheels[-1]


def _install_wheel(wheel: Path) -> None:
    """Install a wheel into the running Python, skipping its dependencies.

    Skips installation if the package is already installed (checked via uv pip show).
    """
    # Extract distribution name from wheel filename
    # (e.g., 'simple_provider-0.1.0-py3-none-any.whl' -> 'simple-provider')
    dist_name = wheel.name.split('-')[0].replace('_', '-')

    # Check if already installed using uv pip show (more reliable than import for namespace packages)
    result = subprocess.run(  # noqa: S603 - test code, no user input
        ['uv', 'pip', 'show', '--python', sys.executable, dist_name],  # noqa: S607 - test code
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return  # Already installed, skip

    subprocess.run(  # noqa: S603 - hardcoded install args, no user input
        [  # noqa: S607 - uv is a known tool resolved from PATH
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
    subprocess.run(  # noqa: S603 - hardcoded uninstall args, no user input
        ['uv', 'pip', 'uninstall', '--python', sys.executable, dist_name],  # noqa: S607 - uv is a known tool resolved from PATH
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


def _discover_providers(examples_dir: Path) -> list[ProviderSpec]:
    """Recursively find all installable providers under ``examples_dir``.

    A directory is treated as a provider package when its ``pyproject.toml``
    contains a ``[project]`` table (i.e. it is not a bare workspace root).

    The dist name is read from ``[project].name``.  The importable package
    name is read from ``[tool.uv.build-backend] module-name`` when present
    (namespace packages such as ``devkit.python``); otherwise it falls back to
    ``dist_name.replace('-', '_')`` which covers simple single-package layouts.
    """
    specs: list[ProviderSpec] = []
    for pyproject in sorted(examples_dir.rglob('pyproject.toml')):
        data = tomllib.loads(pyproject.read_text(encoding='utf-8'))
        if 'project' not in data:
            continue  # workspace root or non-package
        dist_name: str = data['project']['name']
        import_path: str = data.get('tool', {}).get('uv', {}).get(
            'build-backend',
            {},
        ).get('module-name') or dist_name.replace('-', '_')
        specs.append(
            ProviderSpec(
                source_dir=pyproject.parent,
                dist_name=dist_name,
                import_path=import_path,
            ),
        )
    return specs


@pytest.fixture(scope='session', autouse=True)
def installed_providers(
    pytestconfig: pytest.Config,
) -> Generator[InstalledProviders, None, None]:
    """Return installed provider info for integration tests.

    Providers are built and installed once by pytest_configure_node() in the
    root conftest before any workers start. This fixture just returns the
    provider info for test use.

    Cleanup is skipped when running with xdist to avoid race conditions.
    """
    # Detect if running with xdist
    using_xdist = 'PYTEST_XDIST_WORKER' in os.environ

    specs = _discover_providers(_EXAMPLES_DIR)

    providers: dict[str, InstalledProvider] = {
        spec.dist_name: InstalledProvider(
            root=_pkg_sub_path(spec.import_path, 'resources/templates'),
        )
        for spec in specs
    }

    yield InstalledProviders(
        venv_bin=Path(sys.executable).parent,
        providers=providers,
    )

    # Skip cleanup when running with xdist to avoid race conditions
    if not using_xdist:
        for spec in specs:
            _uninstall_package(spec.dist_name)
        shutil.rmtree(_DIST_DIR, ignore_errors=True)
