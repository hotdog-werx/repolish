from pathlib import Path

from repolish.cli.main import app
from repolish.cli.testing import CliRunner

runner = CliRunner()


def test_scaffold_help() -> None:
    result = runner.invoke(app, ['scaffold', '--help'])
    assert result.exit_code == 0
    assert 'NAME' in result.output
    assert '--output-dir' in result.output


def test_scaffold_creates_files(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ['scaffold', 'my-provider', '--output-dir', str(tmp_path)],
    )
    assert result.exit_code == 0
    assert (tmp_path / 'pyproject.toml').exists()
    assert (tmp_path / 'my_provider' / 'repolish' / 'provider.py').exists()


def test_scaffold_idempotent(tmp_path: Path) -> None:
    runner.invoke(
        app,
        ['scaffold', 'my-provider', '--output-dir', str(tmp_path)],
    )
    result = runner.invoke(
        app,
        ['-v', 'scaffold', 'my-provider', '--output-dir', str(tmp_path)],
    )
    assert result.exit_code == 0
    assert 'nothing to write' in result.output
