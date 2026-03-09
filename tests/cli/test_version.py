from typer.testing import CliRunner

from repolish.cli.main import app
from repolish.version import __version__

runner = CliRunner()


def test_main_version_prints_and_exits() -> None:
    result = runner.invoke(app, ['--version'])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_main_no_subcommand_prints_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert 'Usage' in result.output
