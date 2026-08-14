import json
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

from .integration.conftest import (
    _DIST_DIR,
    _EXAMPLES_DIR,
    _build_wheel,
    _discover_providers,
    _install_wheel,
)


def pytest_configure() -> None:
    """Build/install test providers once before any tests run.

    Uses a marker file to ensure providers are only built once,
    even when multiple pytest processes start (xdist workers).
    """
    # Use a marker file to ensure idempotency across workers
    marker = _DIST_DIR / '.providers-ready'
    if marker.exists():
        return  # Already done

    # Build and install all providers once
    _DIST_DIR.mkdir(parents=True, exist_ok=True)
    specs = _discover_providers(_EXAMPLES_DIR)
    for spec in specs:
        pkg_name = spec.dist_name.replace('-', '_')
        wheel = _build_wheel(spec.source_dir, _DIST_DIR, pkg_name)
        _install_wheel(wheel)

    marker.touch()


def _git(*args: str, cwd: Path) -> None:
    """Run git command silently in given directory."""
    subprocess.run(  # noqa: S603
        ['git', *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def init_git_repo(
    path: Path,
    *,
    owner: str = 'test-owner',
    repo: str = 'test-repo',
) -> None:
    """Initialise a bare-minimum git repo so git-dependent provider code doesn't fail.

    Sets up ``origin`` with a GitHub HTTPS URL so ``get_owner_repo()`` can
    parse the owner and repo name.  Uses ``--initial-branch=main`` to avoid
    warnings about default branch names.
    """
    _git('init', '--initial-branch=main', cwd=path)
    _git(
        'config',
        'remote.origin.url',
        f'https://github.com/{owner}/{repo}',
        cwd=path,
    )
    _git('config', 'user.email', 'test@example.com', cwd=path)
    _git('config', 'user.name', 'Test User', cwd=path)
    (path / '.gitignore').write_text('.repolish/\n', encoding='utf-8')


def write_repolish_config(path: Path, config: dict) -> None:
    """Write repolish.yaml configuration file."""
    (path / 'repolish.yaml').write_text(
        json.dumps(config, indent=2),
        encoding='utf-8',
    )


@pytest.fixture
def make_provider(tmp_path: Path):
    """Return a helper that writes a provider module and returns its path.

    The returned callable has signature `(src: str, name: str='prov')->str`.
    """

    def _inner(src: str, name: str = 'prov') -> str:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / 'repolish.py').write_text(dedent(src))
        return str(d)

    return _inner


@pytest.fixture
def temp_repolish_dirs(tmp_path: Path) -> list[str]:
    """Create temporary directories with valid repolish.py files."""
    # Create first directory with repolish.py
    dir1 = tmp_path / 'template1'
    dir1.mkdir()
    repolish_py1 = dir1 / 'repolish.py'
    (dir1 / 'repolish').mkdir(parents=True, exist_ok=True)
    repolish_py1.write_text(
        dedent("""
        def create_context():
            return {
                "name": "Template1",
                "version": "1.0",
                "author": "Test Author",
                "language": "will be overridden"
            }
    """),
    )

    # Create second directory with repolish.py
    dir2 = tmp_path / 'template2'
    dir2.mkdir()
    repolish_py2 = dir2 / 'repolish.py'
    (dir2 / 'repolish').mkdir(parents=True, exist_ok=True)
    repolish_py2.write_text(
        dedent("""
        def create_context():
            return {
                "description": "A test template",
                "license": "MIT",
                "year": 2023
            }
    """),
    )

    # Create third directory with repolish.py
    dir3 = tmp_path / 'template3'
    dir3.mkdir()
    repolish_py3 = dir3 / 'repolish.py'
    (dir3 / 'repolish').mkdir(parents=True, exist_ok=True)
    repolish_py3.write_text(
        dedent("""
        def create_context():
            return {
                "framework": "pytest",
                "language": "python"
            }
    """),
    )

    return [str(dir1), str(dir2), str(dir3)]
