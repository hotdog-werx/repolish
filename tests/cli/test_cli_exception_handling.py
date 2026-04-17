import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish.cli.main import app
from repolish.cli.testing import CliRunner

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
            error_has='Either cli or provider_root must be provided',
        ),
        CLITestCase(
            name='link_resources_dir_without_provider_root',
            args=['link', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    resources_dir: ./resources
                    cli: some-link-cli
                """),
            error_has='resources_dir requires provider_root to be set',
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

    with pytest.raises(Exception) as exc_info:  # noqa: PT011 - exception type varies per parametrized case; checking type here would duplicate the parametrize data
        runner.invoke(app, args, catch_exceptions=False)

    if case.error_has:
        assert case.error_has in str(exc_info.value)
