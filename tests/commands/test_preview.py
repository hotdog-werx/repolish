import io
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

from repolish.commands.preview import command as run_debug


def test_run_debug_basic(tmp_path: Path):
    """Test basic debug functionality."""
    debug_file = tmp_path / 'debug.yaml'
    debug_file.write_text(
        textwrap.dedent("""\
        template: |
          ## repolish-start[example] ##
          default content
          ## repolish-end[example] ##

        config:
          anchors:
            example: "replaced content"
        """),
        encoding='utf-8',
    )

    # Capture stdout

    f = io.StringIO()
    with redirect_stdout(f):
        result = run_debug(debug_file, show_patterns=False, show_steps=False)

    output = f.getvalue()
    assert result == 0
    assert 'replaced content' in output


def test_run_debug_with_regex(tmp_path: Path):
    """Test debug with regex replacement."""
    debug_file = tmp_path / 'debug.yaml'
    debug_file.write_text(
        textwrap.dedent("""\
        template: |
          version = "0.0.0"
          ## repolish-regex[version]: version = "(.+)"

        target: |
          version = "1.2.3"
        """),
        encoding='utf-8',
    )

    f = io.StringIO()
    with redirect_stdout(f):
        result = run_debug(debug_file, show_patterns=False, show_steps=False)

    output = f.getvalue()
    assert result == 0
    assert 'version = "1.2.3"' in output


def test_run_debug_show_patterns(tmp_path: Path):
    """Test debug with show patterns option."""
    debug_file = tmp_path / 'debug.yaml'
    debug_file.write_text(
        textwrap.dedent("""\
        template: |
          ## repolish-start[example] ##
          default content
          ## repolish-end[example] ##

          ## repolish-regex[version]: version = "(.+)"

        target: |
          version = "1.2.3"
        """),
        encoding='utf-8',
    )

    f = io.StringIO()
    with redirect_stdout(f):
        result = run_debug(debug_file, show_patterns=True, show_steps=False)

    output = f.getvalue()
    assert result == 0
    assert 'extracted_patterns' in output
    # Check for content in either Python dict repr format or YAML format
    assert 'example' in output
    assert 'default content' in output
    assert 'version' in output
    assert 'version = "(.+)"' in output


def test_run_debug_missing_template(tmp_path: Path):
    """Test debug with missing template key."""
    debug_file = tmp_path / 'debug.yaml'
    debug_file.write_text(
        textwrap.dedent("""\
        target: "some target"
        """),
        encoding='utf-8',
    )

    result = run_debug(debug_file, show_patterns=False, show_steps=False)
    assert result == 1
