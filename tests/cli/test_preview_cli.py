import textwrap
from pathlib import Path

import pytest

from repolish.cli.main import app
from repolish.cli.testing import CliRunner

runner = CliRunner()


def test_integration_debug_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration test for the debug CLI with a full debug configuration."""
    debug_file = tmp_path / 'debug.yaml'
    debug_file.write_text(
        textwrap.dedent("""\
        template: |
          # My Project
          ## repolish-start[header] ##
          Default header content
          ## repolish-end[header] ##

          version = "0.0.0"
          ## repolish-regex[version]: version = "(.+)"

        target: |
          version = "1.2.3"

        config:
          anchors:
            header: |
              Custom header
              with multiple lines
        """),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ['preview', str(debug_file), '--show-patterns', '--show-steps'],
    )
    assert result.exit_code == 0
