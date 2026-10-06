import io
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from pydantic import ValidationError

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

          ## repolish-keep-rest[repo-overrides]: marker="## repo-overrides"
          ## repo-overrides
          # Placeholder

          ## repolish-regex[version]: version = "(.+)"

        target: |
          ## repo-overrides
          custom=true
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
    assert 'keep_rest' in output
    assert 'repo-overrides' in output
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

    with pytest.raises(ValidationError) as exc_info:
        run_debug(debug_file, show_patterns=False, show_steps=False)

    assert 'template' in str(exc_info.value)
    assert 'Field required' in str(exc_info.value)


def _run_scratch(
    tmp_path: Path,
    content: str,
    *,
    show_steps: bool = False,
) -> tuple[int, str]:
    """Write the scratch YAML and return (exit code, captured stdout)."""
    debug_file = tmp_path / 'debug.yaml'
    debug_file.write_text(textwrap.dedent(content), encoding='utf-8')
    f = io.StringIO()
    with redirect_stdout(f):
        result = run_debug(debug_file, show_patterns=False, show_steps=show_steps)
    return result, f.getvalue()


def test_preview_renders_jinja_context(tmp_path: Path):
    """config.context feeds the Jinja render stage."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          python_version = "{{ python_version }}"

        config:
          context:
            python_version: "3.12"
        """,
    )

    assert result == 0
    assert 'python_version = "3.12"' in output


def test_preview_after_render_keep_block_in_jinja_loop(tmp_path: Path):
    """|after-render keep blocks reconcile against the target after Jinja."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          ## repolish:keep-block[paths|after-render] start="# additional-paths" end-regex="^provider[0-9]+:$"
          {% for idx in providers %}
          provider{{ idx }}:
             - static{{ idx }}
             # additional-paths
             - default{{ idx }}
          {% endfor %}

        target: |
          provider1:
             - static1
             # additional-paths
             - custom1
          provider2:
             - static2
             # additional-paths
             - custom2

        config:
          context:
            providers: [1, 2]
        """,
    )

    assert result == 0
    assert 'repolish:keep-block' not in output
    assert 'custom1' in output
    assert 'custom2' in output
    assert 'default1' not in output


def test_preview_after_render_regex_pairs_dependency_versions(tmp_path: Path):
    """|after-render regex pairs loop-generated deps; new entries keep defaults."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          ## repolish:regex[deps|after-render] ^[ \\t]*- \\w+==(.+)$
          {% for dep in deps %}
            - {{ dep }}==0.0.0
          {% endfor %}

        target: |
          - alpha==1.2.3
          - beta==4.5.6

        config:
          context:
            deps: [alpha, beta, gamma]
        """,
    )

    assert result == 0
    assert 'repolish:regex' not in output
    assert 'alpha==1.2.3' in output
    assert 'beta==4.5.6' in output
    assert 'gamma==0.0.0' in output
    assert 'alpha==0.0.0' not in output
    assert 'beta==0.0.0' not in output


def test_preview_fills_insertion_blocks(tmp_path: Path):
    """config.insertions.functions fills repolish:on blocks."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          <!-- repolish:on:footer display-year -->
          old body
          <!-- repolish:off:footer -->

        config:
          insertions:
            functions:
              display-year: "2026"
        """,
    )

    assert result == 0
    assert '2026' in output
    assert 'old body' not in output


def test_preview_insertion_functions_receive_marker_args(tmp_path: Path):
    """Function bodies are Jinja templates with the marker args as `args`."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          # repolish:on:env show-env staging
          body
          # repolish:off:env

        config:
          context:
            env_label: Environment
          insertions:
            functions:
              show-env: "{{ args[0] }} {{ env_label }}"
        """,
    )

    assert result == 0
    assert 'staging Environment' in output


def test_preview_insertion_marker_arg_edits_are_adopted(tmp_path: Path):
    """Adoption keeps the target file's marker args when filling from the template."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          # repolish:on:env show-env staging
          body
          # repolish:off:env

        target: |
          # repolish:on:env show-env production
          old body
          # repolish:off:env

        config:
          insertions:
            functions:
              show-env: "{{ args[0] }} environment"
        """,
    )

    assert result == 0
    assert 'show-env production' in output
    assert 'production environment' in output
    assert 'staging' not in output


def test_preview_fills_insertion_zones(tmp_path: Path):
    """repolish:insert zones fill from the declared (or named) function."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          # My Project

          ## repolish:insert[badges] start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"
          <!-- generated:badges:on my-org/my-repo -->
          _Default badge row for new projects._
          <!-- generated:badges:off -->

        config:
          insertions:
            functions:
              badges: "![ci](https://ci.example/{{ args[0] }}/badge.svg)"
        """,
    )

    assert result == 0
    assert 'repolish:insert' not in output
    assert '![ci](https://ci.example/my-org/my-repo/badge.svg)' in output
    assert 'Default badge row' not in output


def test_preview_unknown_insertion_function_reports_diagnostic(tmp_path: Path):
    """A missing renderer surfaces a diagnostic (rc 0); markers survive."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          <!-- repolish:on:footer unknown-fn -->
          original body
          <!-- repolish:off:footer -->
        """,
    )

    assert result == 0
    assert 'unknown-fn' in output
    assert 'insertion_diagnostics' in output


def test_preview_missing_context_variable_fails_cleanly(tmp_path: Path):
    """StrictUndefined mirrors a real apply render failure (rc 1)."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          val = "{{ missing_variable }}"
        """,
    )

    assert result == 1
    assert 'preview_render_failed' in output


def test_preview_show_steps_prints_pipeline_stages(tmp_path: Path):
    """--show-steps shows each intermediate stage, ending at the Result."""
    result, output = _run_scratch(
        tmp_path,
        """\
        template: |
          ## repolish:keep-block[note|after-render] start="<!-- note-on -->" end="<!-- note-off -->"
          Title: {{ title }}
          <!-- note-on -->
          Default
          <!-- note-off -->

        config:
          context:
            title: My Doc
        """,
        show_steps=True,
    )

    assert result == 0
    assert 'Stage: Pre-render (what Jinja receives)' in output
    assert 'Stage: Rendered (after Jinja)' in output
    assert 'Stage: After-render directives' in output
    # an after-render directive survives the pre-render stage untouched
    assert 'keep-block[note|after-render]' in output.split('Stage: Pre-render', maxsplit=1)[1]
    assert 'Title: My Doc' in output
