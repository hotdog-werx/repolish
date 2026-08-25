from pathlib import Path

import pytest

from repolish.cli.main import app
from repolish.cli.testing import CliRunner

runner = CliRunner()


def test_scaffold_help() -> None:
    result = runner.invoke(app, ['scaffold', '--help'])
    assert result.exit_code == 0
    assert 'DIRECTORY' in result.output
    assert '--package' in result.output
    assert '--prefix' in result.output
    assert '--monorepo' in result.output


def test_scaffold_creates_files(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ['scaffold', str(tmp_path), '--package', 'my_provider'],
    )
    assert result.exit_code == 0
    assert (tmp_path / 'pyproject.toml').exists()
    # default (simple) mode: flat provider.py, no provider/ sub-package
    assert (tmp_path / 'my_provider' / 'repolish' / 'provider.py').exists()
    assert not (tmp_path / 'my_provider' / 'repolish' / 'provider').exists()


def test_scaffold_monorepo_creates_mode_handlers(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ['scaffold', str(tmp_path), '--package', 'my_provider', '--monorepo'],
    )
    assert result.exit_code == 0
    provider_dir = tmp_path / 'my_provider' / 'repolish' / 'provider'
    assert (provider_dir / '__init__.py').exists()
    assert (provider_dir / 'root.py').exists()
    assert (provider_dir / 'member.py').exists()
    assert (provider_dir / 'standalone.py').exists()
    assert not (tmp_path / 'my_provider' / 'repolish' / 'provider.py').exists()


def test_scaffold_namespace_package(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ['scaffold', str(tmp_path), '--package', 'devkit.workspace'],
    )
    assert result.exit_code == 0
    pkg = tmp_path / 'devkit' / 'workspace'
    # simple mode: flat provider.py
    assert (pkg / 'repolish' / 'provider.py').exists()
    assert not (pkg / 'repolish' / 'provider').exists()
    assert (pkg / '__init__.py').exists()
    # pyproject uses module-name = "devkit.workspace" and module-root = "."
    pyproject = (tmp_path / 'pyproject.toml').read_text()
    assert 'module-name = "devkit.workspace"' in pyproject
    assert 'module-root = "."' in pyproject
    assert 'devkit-workspace-link' in pyproject
    # imports inside generated files use dot-notation
    provider_init = (pkg / 'repolish' / '__init__.py').read_text()
    assert 'from devkit.workspace.repolish' in provider_init


def test_scaffold_namespace_package_monorepo(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            'scaffold',
            str(tmp_path),
            '--package',
            'devkit.workspace',
            '--monorepo',
        ],
    )
    assert result.exit_code == 0
    provider_dir = tmp_path / 'devkit' / 'workspace' / 'repolish' / 'provider'
    assert (provider_dir / '__init__.py').exists()
    assert (provider_dir / 'root.py').exists()
    assert (provider_dir / 'member.py').exists()
    assert (provider_dir / 'standalone.py').exists()


def test_scaffold_idempotent(tmp_path: Path) -> None:
    runner.invoke(
        app,
        ['scaffold', str(tmp_path), '--package', 'my_provider'],
    )
    result = runner.invoke(
        app,
        ['-v', 'scaffold', str(tmp_path), '--package', 'my_provider'],
    )
    assert result.exit_code == 0
    assert 'nothing to write' in result.output


def test_scaffold_local_defaults_to_internal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--local with no DIRECTORY scaffolds internal/: alias local, class LocalProvider."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ['scaffold', '--local'])
    assert result.exit_code == 0
    templates = tmp_path / 'internal' / 'templates'
    assert (templates / 'repolish.py').exists()
    assert (templates / 'repolish' / 'some-template.md.jinja').exists()

    content = (templates / 'repolish.py').read_text()
    assert 'class LocalProviderContext(BaseContext):' in content
    assert 'class LocalProvider(Provider[LocalProviderContext, BaseInputs]):' in content
    assert 'local:' in content
    assert 'provider_root: internal/templates' in content

    # the printed repolish.yaml snippet matches the convention
    assert 'provider_root: internal/templates' in result.output


def test_scaffold_local_explicit_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A given DIRECTORY only relocates the provider; identity stays local/LocalProvider."""
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / 'ops'
    result = runner.invoke(app, ['scaffold', 'ops', '--local'])
    assert result.exit_code == 0
    assert (dest / 'templates' / 'repolish.py').exists()
    # no package artifacts
    assert not list(dest.glob('*.toml'))

    content = (dest / 'templates' / 'repolish.py').read_text()
    assert 'class LocalProvider(Provider[LocalProviderContext, BaseInputs]):' in content
    assert 'provider_root: ops/templates' in content


def test_scaffold_local_installable_tier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--local --installable adds pyproject.toml + internal package and shims repolish.py."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ['scaffold', 'internal', '--local', '--installable'],
    )
    assert result.exit_code == 0
    base = tmp_path / 'internal'
    assert (base / 'pyproject.toml').exists()
    assert (base / 'internal' / '__init__.py').exists()
    provider = base / 'internal' / 'provider.py'
    assert provider.exists()
    assert 'class LocalProvider(Provider[LocalProviderContext, BaseInputs]):' in provider.read_text()

    shim = (base / 'templates' / 'repolish.py').read_text()
    assert 'from internal import __version__' in shim
    assert 'from internal.provider import LocalProvider' in shim
    assert 'class LocalProvider' not in shim

    # installable tier needs the editable-install hint (output is line-wrapped)
    assert 'editable-install' in result.output
    assert '-e' in result.output
    assert './internal' in result.output


def test_scaffold_installable_requires_local(tmp_path: Path) -> None:
    """--installable without --local is rejected."""
    result = runner.invoke(
        app,
        ['scaffold', str(tmp_path / 'internal'), '--installable'],
    )
    assert result.exit_code == 1


def test_scaffold_local_rejects_package_option(tmp_path: Path) -> None:
    """--package and --local are mutually exclusive."""
    result = runner.invoke(
        app,
        [
            'scaffold',
            str(tmp_path / 'internal'),
            '--local',
            '--package',
            'x',
        ],
    )
    assert result.exit_code == 1


def test_scaffold_local_rejects_monorepo(tmp_path: Path) -> None:
    """--monorepo cannot be combined with --local."""
    result = runner.invoke(
        app,
        ['scaffold', str(tmp_path / 'internal'), '--local', '--monorepo'],
    )
    assert result.exit_code == 1


def test_scaffold_without_local_requires_directory() -> None:
    """Without --local, DIRECTORY is required."""
    result = runner.invoke(app, ['scaffold', '--package', 'my_provider'])
    assert result.exit_code == 1


def test_scaffold_package_requires_package_option(tmp_path: Path) -> None:
    """Without --local, --package is still required."""
    result = runner.invoke(app, ['scaffold', str(tmp_path / 'dest')])
    assert result.exit_code == 1
