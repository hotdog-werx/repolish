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


def test_after_render_keep_block_preserves_only_matching_repeated_regions_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated keep blocks preserve only edited local regions in occurrence order."""
    _write(
        tmp_path / 'CONFIG.yaml',
        """\
        provider1:
          - 'static1'
          # additional
          # end-additional
        provider2:
          - 'static2'
          # additional
          # end-additional
        provider3:
          - 'static3'
          # additional
          # end-additional
        provider4:
          - 'static4'
          # additional
          # end-additional
        provider5:
          - 'static5'
          # additional
          # end-additional
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import TemplateMapping


        class Ctx(BaseContext):
            providers: list[int] = [1, 2, 3, 4, 5]


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {
                    'CONFIG.yaml': TemplateMapping(source_template='CONFIG.yaml.jinja'),
                }
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'CONFIG.yaml.jinja',
        """\
        ## repolish-keep-block[provider-additional|after-render]: start="# additional" end="# end-additional"
        {% for idx in providers %}
        provider{{ idx }}:
          - 'static{{ idx }}'
          # additional
          # end-additional
        {% endfor %}
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

    run_repolish(['apply'], exit_code=0)

    first_pass = (tmp_path / 'CONFIG.yaml').read_text(encoding='utf-8')
    edited = first_pass.replace(
        "provider1:\n  - 'static1'\n  # additional\n  # end-additional\n",
        "provider1:\n  - 'static1'\n  # additional\n  - 'custom1'\n  # end-additional\n",
    ).replace(
        "provider3:\n  - 'static3'\n  # additional\n  # end-additional\n",
        "provider3:\n  - 'static3'\n  # additional\n  - 'custom3'\n  # end-additional\n",
    )
    (tmp_path / 'CONFIG.yaml').write_text(edited, encoding='utf-8')

    run_repolish(['apply'], exit_code=0)

    out = (tmp_path / 'CONFIG.yaml').read_text(encoding='utf-8')

    assert "provider1:\n  - 'static1'\n  # additional\n  - 'custom1'\n  # end-additional\n" in out
    assert "provider3:\n  - 'static3'\n  # additional\n  - 'custom3'\n  # end-additional\n" in out

    assert "provider2:\n  - 'static2'\n  # additional\n  # end-additional\n" in out
    assert "provider4:\n  - 'static4'\n  # additional\n  # end-additional\n" in out
    assert "provider5:\n  - 'static5'\n  # additional\n  # end-additional\n" in out


def test_after_render_multiregex_preserves_only_selected_provider_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After-render multiregex with one shared tag preserves edited entries."""
    block_pattern = r'^\[custom-provider-additions\](.*?)(?=\n\[|\Z)'

    _write(
        tmp_path / 'CONFIG.ini',
        """\
        [custom-provider-additions]
        provider1 = ""
        provider2 = ""
        provider3 = ""
        provider4 = ""
        provider5 = ""
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider
        from repolish.providers.models import TemplateMapping


        class Ctx(BaseContext):
            providers: list[int] = [1, 2, 3, 4, 5]


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {
                    'CONFIG.ini': TemplateMapping(source_template='CONFIG.ini.jinja'),
                }
        """,
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'CONFIG.ini.jinja',
        dedent(
            f"""\
            ## repolish-multiregex-block[custom-provider-additions|after-render]: {block_pattern}
            ## repolish-multiregex[custom-provider-additions|after-render]: ^(")?([^"=\\s]+)(")?\\s*=\\s*"([^"]*)"$

            [custom-provider-additions]
            {{% for idx in providers %}}
            provider{{{{ idx }}}} = ""
            {{% endfor %}}
            """,
        ),
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

    run_repolish(['apply'], exit_code=0)

    first_pass = (tmp_path / 'CONFIG.ini').read_text(encoding='utf-8')
    edited = first_pass.replace(
        'provider1 = ""\n',
        'provider1 = "custom1"\n',
    ).replace(
        'provider3 = ""\n',
        'provider3 = "custom3"\n',
    )
    (tmp_path / 'CONFIG.ini').write_text(edited, encoding='utf-8')

    run_repolish(['apply'], exit_code=0)

    out = (tmp_path / 'CONFIG.ini').read_text(encoding='utf-8')

    assert 'provider1 = "custom1"' in out
    assert 'provider3 = "custom3"' in out
    assert 'provider2 = ""' in out
    assert 'provider4 = ""' in out
    assert 'provider5 = ""' in out
