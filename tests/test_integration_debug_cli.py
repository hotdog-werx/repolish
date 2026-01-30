import os
import textwrap
from pathlib import Path

from pytest_mock import MockerFixture

from repolish.debug_cli import main


def test_integration_debug_cli(tmp_path: Path, mocker: MockerFixture) -> None:
    """Integration test for the debug CLI with a full debug configuration."""
    # Create a debug.yaml file with template, target, and config
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

    mocker.patch(
        'sys.argv',
        [
            'repolish-debugger',
            str(debug_file),
            '--show-patterns',
            '--show-steps',
        ],
    )

    # Change to tmp_path so relative paths work
    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        # Mock sys.argv to simulate command line arguments

        result = main()
        assert result == 0
    finally:
        os.chdir(old_cwd)
