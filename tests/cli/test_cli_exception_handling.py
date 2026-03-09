import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repolish.cli.main import app

runner = CliRunner()


@dataclass
class CLITestCase:
    """Test case for CLI exception handling."""

    name: str
    args: list[str]
    config_content: str
    config_filename: str = 'repolish.yaml'
    error_has: str = ''


@pytest.mark.parametrize(
    'case',
    [
        CLITestCase(
            name='cli_invalid_provider_config',
            args=['apply', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    link: some-link-cli
                """),
            error_has='Either cli or directory must be provided',
        ),
        CLITestCase(
            name='link_both_cli_and_directory',
            args=['link', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    cli: some-link-cli
                    directory: ./templates
                """),
            error_has='Cannot specify both cli and directory',
        ),
        CLITestCase(
            name='preview_missing_template',
            args=['preview', '{config_path}'],
            config_content=textwrap.dedent("""\
                target: |
                  some content
                config:
                  anchors: {}
                """),
            config_filename='debug.yaml',
            error_has='Field required',
        ),
    ],
    ids=lambda case: case.name,
)
def test_cli_exception_handling(
    case: CLITestCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that CLI raises errors when configuration is invalid."""
    config_file = tmp_path / case.config_filename
    config_file.write_text(case.config_content, encoding='utf-8')

    args = [arg.replace('{config_path}', str(config_file)) for arg in case.args]

    monkeypatch.chdir(tmp_path)

    with pytest.raises(Exception) as exc_info:  # noqa: PT011
        runner.invoke(app, args, catch_exceptions=False)

    if case.error_has:
        assert case.error_has in str(exc_info.value)
