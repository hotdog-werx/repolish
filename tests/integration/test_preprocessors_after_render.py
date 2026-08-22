from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from pytest_mock import MockerFixture


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding='utf-8')


def test_after_render_keep_block_preserves_loop_generated_local_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """phase=after-render keeps developer edits for loop-generated blocks."""
    _write(
        tmp_path / 'NOTES.md',
        """\
        - alpha
        <!-- note-start -->
        custom alpha note
        <!-- note-end -->
        - beta
        <!-- note-start -->
        custom beta note
        <!-- note-end -->
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import TemplateMapping


        class Ctx(BaseContext):
            items: list[str] = ['alpha', 'beta']


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {
                    'NOTES.md': TemplateMapping(source_template='NOTES.md.jinja'),
                }
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'NOTES.md.jinja',
        """\
        ## repolish-keep-block[user-note|after-render]: start="<!-- note-start -->" end="<!-- note-end -->"
        {%- for item in items %}
        - {{ item }}
        <!-- note-start -->
        default {{ item }} note
        <!-- note-end -->
        {%- endfor %}
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected = dedent(
        """\
        - alpha
        <!-- note-start -->
        custom alpha note
        <!-- note-end -->
        - beta
        <!-- note-start -->
        custom beta note
        <!-- note-end -->
        """,
    )

    content = (tmp_path / 'NOTES.md').read_text(encoding='utf-8')
    assert content.strip() == expected.strip()
    assert 'repolish-keep-block' not in content
    assert 'NOTES.md' in result.output


def test_apply_invalid_regex_phase_suffix_logs_warning_and_falls_back_to_pre_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """Invalid regex phase suffix warns and still behaves as pre-render."""
    _write(
        tmp_path / 'pyproject.toml',
        """\
        [project]
        version = "1.2.3"
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import TemplateMapping


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {
                    'pyproject.toml': TemplateMapping(source_template='pyproject.toml.jinja'),
                }
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'pyproject.toml.jinja',
        """\
        [project]
        ## repolish-regex[version|oops-render]: ^version = \"(.+?)\"$
        version = "0.0.0"
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    warn_mock = mocker.patch(
        'repolish.preprocessors.directive_phase.logger.warning',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'], exit_code=0)

    output = (tmp_path / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'version = "1.2.3"' in output

    warning_calls = [
        call for call in warn_mock.call_args_list if call.args and call.args[0] == 'directive_invalid_phase_suffix'
    ]
    assert warning_calls
    assert any(
        call.kwargs.get('tag') == 'version|oops-render' and call.kwargs.get('source_path') for call in warning_calls
    )


def test_apply_invalid_keep_phase_suffix_logs_warning_and_falls_back_to_pre_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """Invalid keep-block phase suffix warns and still behaves as pre-render."""
    _write(
        tmp_path / 'NOTES.md',
        """\
        # Notes
        <!-- note-start -->
        custom text
        <!-- note-end -->
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import TemplateMapping


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {
                    'NOTES.md': TemplateMapping(source_template='NOTES.md.jinja'),
                }
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'NOTES.md.jinja',
        """\
        # Notes
        ## repolish-keep-block[user-note|oops-render]: start="<!-- note-start -->" end="<!-- note-end -->"
        <!-- note-start -->
        default text
        <!-- note-end -->
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    warn_mock = mocker.patch(
        'repolish.preprocessors.directive_phase.logger.warning',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'], exit_code=0)

    output = (tmp_path / 'NOTES.md').read_text(encoding='utf-8')
    assert 'custom text' in output
    assert 'default text' not in output

    warning_calls = [
        call for call in warn_mock.call_args_list if call.args and call.args[0] == 'directive_invalid_phase_suffix'
    ]
    assert warning_calls
    assert any(
        call.kwargs.get('tag') == 'user-note|oops-render' and call.kwargs.get('source_path') for call in warning_calls
    )


def test_apply_invalid_multiregex_phase_suffix_logs_warning_and_falls_back_to_pre_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
) -> None:
    """Invalid multiregex phase suffix warns and still behaves as pre-render."""
    _write(
        tmp_path / 'toolbelt.toml',
        """\
        [tools]
        uv = "0.7.20"
        dprint = "0.50.1"
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import TemplateMapping


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {
                    'toolbelt.toml': TemplateMapping(source_template='toolbelt.toml.jinja'),
                }
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'toolbelt.toml.jinja',
        r"""\
        [tools]
        ## repolish-multiregex-block[tools|oops-render]: ^\[tools\](.*?)(?=\n\[|\Z)
        ## repolish-multiregex[tools|oops-render]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
        uv = "0.0.0"
        dprint = "0.0.0"
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    warn_mock = mocker.patch(
        'repolish.preprocessors.directive_phase.logger.warning',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'], exit_code=0)

    output = (tmp_path / 'toolbelt.toml').read_text(encoding='utf-8')
    assert 'uv = "0.7.20"' in output
    assert 'dprint = "0.50.1"' in output

    warning_calls = [
        call for call in warn_mock.call_args_list if call.args and call.args[0] == 'directive_invalid_phase_suffix'
    ]
    assert warning_calls
    assert any(call.kwargs.get('tag') == 'tools|oops-render' for call in warning_calls)
