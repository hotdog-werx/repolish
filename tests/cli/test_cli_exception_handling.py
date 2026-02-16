import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from repolish.cli.main import app as cli_main
from repolish.cli.standalone.link_cli import app as link_cli_main
from repolish.cli.standalone.preview_cli import app as debug_cli_main


@dataclass
class CLITestCase:
    """Test case for CLI exception handling."""

    name: str
    main_func: Callable
    argv: list[str]
    config_content: str
    config_filename: str = 'repolish.yaml'
    error_has: str = ''


@pytest.mark.parametrize(
    'case',
    [
        CLITestCase(
            name='cli_invalid_provider_config',
            main_func=cli_main,
            argv=['repolish', 'apply', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    link: some-link-cli
                """),
            error_has='Either cli or directory must be provided',
        ),
        # REMOVE later when standalone apps are removed
        CLITestCase(
            name='cli_invalid_provider_config',
            main_func=cli_main,
            argv=['repolish', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    link: some-link-cli
                """),
            error_has='Either cli or directory must be provided',
        ),
        CLITestCase(
            name='link_both_cli_and_directory',
            main_func=cli_main,
            argv=['repolish', 'link', '--config', '{config_path}'],
            config_content=textwrap.dedent("""\
                providers:
                  some-provider:
                    cli: some-link-cli
                    directory: ./templates
                """),
            error_has='Cannot specify both cli and directory',
        ),
        # REMOVE later when link CLI is removed
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
            error_has='Cannot specify both cli and directory',
        ),
        CLITestCase(
            name='preview_missing_template',
            main_func=cli_main,
            argv=['repolish', 'preview', '{config_path}'],
            config_content=textwrap.dedent("""\
                target: |
                  some content
                config:
                  anchors: {}
                """),
            config_filename='debug.yaml',
            error_has='Field required',
        ),
        # REMOVE later when debug CLI is removed
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
            error_has='Field required',
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
    """Test that CLI shows errors when configuration is invalid."""
    # Create the config file
    config_file = tmp_path / case.config_filename
    config_file.write_text(case.config_content, encoding='utf-8')

    # Substitute the config path in argv
    argv = [arg.replace('{config_path}', str(config_file)) for arg in case.argv]

    monkeypatch.chdir(tmp_path)
    mocker.patch('sys.argv', argv)

    with pytest.raises(Exception) as exc_info:  # noqa: PT011 -- making sure we fail
        case.main_func()

    if case.error_has:
        assert case.error_has in str(exc_info.value)
