import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from repolish.cli import main as cli_main
from repolish.debug_cli import main as debug_cli_main
from repolish.link_cli import main as link_cli_main


@dataclass
class CLITestCase:
    """Test case for CLI exception handling."""

    name: str
    main_func: Callable
    argv: list[str]
    config_content: str
    config_filename: str = 'repolish.yaml'


@pytest.mark.parametrize(
    'case',
    [
        CLITestCase(
            name='cli_invalid_provider_config',
            main_func=cli_main,
            argv=['repolish', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    link: some-link-cli
                """),
        ),
        CLITestCase(
            name='link_cli_both_cli_and_directory',
            main_func=link_cli_main,
            argv=['repolish-link', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    cli: some-link-cli
                    directory: ./templates
                """),
        ),
        CLITestCase(
            name='debug_cli_missing_template',
            main_func=debug_cli_main,
            argv=['repolish-debugger', '{config_path}'],
            config_content=textwrap.dedent("""\
                target: |
                  some content
                config:
                  anchors: {}
                """),
            config_filename='debug.yaml',
        ),
    ],
    ids=lambda case: case.name,
)
def test_cli_exception_handling(
    case: CLITestCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """Test that CLI exits with code 1 when configuration is invalid."""
    # Create the config file
    config_file = tmp_path / case.config_filename
    config_file.write_text(case.config_content, encoding='utf-8')

    # Substitute the config path in argv
    argv = [arg.replace('{config_path}', str(config_file)) for arg in case.argv]

    monkeypatch.chdir(tmp_path)
    mocker.patch('sys.argv', argv)

    rv = case.main_func()

    # Should exit with error code 1
    assert rv == 1
