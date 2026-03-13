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
