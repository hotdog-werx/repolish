from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
