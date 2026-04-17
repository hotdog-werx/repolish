from repolish.cli.main import app
from repolish.cli.testing import CliRunner
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


def test_invoke_with_no_args_defaults_to_empty_list() -> None:
    """CliRunner.invoke handles args=None by defaulting to an empty list."""
    result = runner.invoke(app)
    assert result.exit_code == 0
    assert 'Usage' in result.output
