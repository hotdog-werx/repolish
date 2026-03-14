from pathlib import Path

from repolish.cli.main import app
from repolish.cli.testing import CliRunner

runner = CliRunner()


def test_scaffold_help() -> None:
    result = runner.invoke(app, ['scaffold', '--help'])
    assert result.exit_code == 0
    assert 'DIRECTORY' in result.output
    assert '--package' in result.output
    assert '--prefix' in result.output


def test_scaffold_creates_files(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ['scaffold', str(tmp_path), '--package', 'my_provider'],
    )
    assert result.exit_code == 0
    assert (tmp_path / 'pyproject.toml').exists()
    assert (tmp_path / 'my_provider' / 'repolish' / 'provider.py').exists()


def test_scaffold_namespace_package(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ['scaffold', str(tmp_path), '--package', 'devkit.workspace'],
    )
    assert result.exit_code == 0
    # Package files placed under devkit/workspace/
    assert (tmp_path / 'devkit' / 'workspace' / 'repolish' / 'provider.py').exists()
    assert (tmp_path / 'devkit' / 'workspace' / '__init__.py').exists()
    # pyproject uses module-name = "devkit.workspace" and module-root = "."
    pyproject = (tmp_path / 'pyproject.toml').read_text()
    assert 'module-name = "devkit.workspace"' in pyproject
    assert 'module-root = "."' in pyproject
    assert 'devkit-workspace-link' in pyproject
    # imports inside generated files use dot-notation
    provider_init = (tmp_path / 'devkit' / 'workspace' / 'repolish' / '__init__.py').read_text()
    assert 'from devkit.workspace.repolish' in provider_init


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
