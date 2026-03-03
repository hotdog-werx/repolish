import textwrap
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from repolish.cli.standalone.link_cli import app as link_cli_main
from repolish.cli.standalone.preview_cli import app as debug_cli_main


def test_link_cli_both_cli_and_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    cfg = tmp_path / 'repolish.yaml'
    cfg.write_text(
        textwrap.dedent("""\
providers:
  some-provider:
    cli: some-link-cli
    directory: ./templates
"""),
    )

    argv = ['repolish-link', '--config', str(cfg)]
    monkeypatch.chdir(tmp_path)
    mocker.patch('sys.argv', argv)

    with pytest.raises(
        Exception,
        match='Cannot specify both cli and directory',
    ):
        link_cli_main()


def test_debug_cli_missing_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    cfg = tmp_path / 'debug.yaml'
    cfg.write_text(
        textwrap.dedent("""\
target: |
  some content
config:
  anchors: {}
"""),
    )

    argv = ['repolish-debugger', str(cfg)]
    monkeypatch.chdir(tmp_path)
    mocker.patch('sys.argv', argv)

    with pytest.raises(Exception, match='Field required'):
        debug_cli_main()
