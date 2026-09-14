"""Integration tests for the config-level post_process pipeline.

Scenarios covered:
- A plain provider file (no insertions) is formatted by post_process during
  apply, and check agrees with the result instead of reporting false drift
  (regression: the phases refactor moved the staged post-process after the
  copy into the project, so the project received unformatted content while
  check compared against the formatted staged tree)
- With insertions in play, post_process runs exactly once per session — over
  the render tree, before anything is copied into the project (regression:
  insertion output used to be applied in-place to project files after the
  copy, forcing a second post_process run over the whole project root)
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _make_provider(directory: Path, files: dict[str, str]) -> None:
    """Create a minimal provider that maps each key → template content."""
    for name, content in files.items():
        _write(directory / 'repolish' / name, content)
    _write(
        directory / 'repolish.py',
        """\
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()
        """,
    )


def _make_insertion_provider(
    directory: Path,
    body: str,
    extra_methods: str = '',
) -> None:
    """Create a provider whose create_file_insertions body is *body*."""
    directory.mkdir(parents=True, exist_ok=True)
    body_dedented = textwrap.dedent(body).strip()
    body_indented = '\n'.join(f'        {line}' for line in body_dedented.splitlines())
    methods_text = ''
    if extra_methods:
        methods_dedented = textwrap.dedent(extra_methods).strip()
        methods_text = '\n'.join(f'    {line}' for line in methods_dedented.splitlines())
    (directory / 'repolish.py').write_text(
        f"""\
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_insertions(self, context):
{body_indented}
{methods_text}
""",
        encoding='utf-8',
    )


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Simulates Unix-style installed CLI execution from PATH.',
)
def test_check_agrees_with_apply_after_post_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After apply formats a file via post_process, check must report no drift.

    The template is two tab-indented lines and post_process rewrites tabs to
    two spaces. Without insertions in play, the only thing that puts the
    formatted content into the project is the staged copy — so the staged tree
    must be post-processed *before* it is copied into the project. Otherwise
    apply writes the tabbed content, check formats its staged copy before
    comparing, and every check run reports drift that apply can never fix.
    """
    # written directly (not via _write) so textwrap.dedent cannot strip the tabs
    template = tmp_path / 'p' / 'repolish' / 'tabbed.txt'
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text('\tline one\n\tline two\n', encoding='utf-8')
    _make_provider(tmp_path / 'p', files={})

    # post_process command: rewrite tabs as two spaces in every txt file in cwd
    script = tmp_path / 'tab_to_spaces.py'
    script.write_text(
        '#!/usr/bin/env python3\n'
        'import pathlib\n'
        'for f in pathlib.Path(".").glob("*.txt"):\n'
        '    f.write_text(f.read_text().replace("\\t", "  "))\n',
        encoding='utf-8',
    )
    script.chmod(0o755)
    old_path = os.environ.get('PATH', '')
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{old_path}')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'post_process': ['tab_to_spaces.py'],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    run_repolish(['apply'], exit_code=0)

    # The project file holds the post-processed content — that is the final
    # file apply is responsible for.
    content = (tmp_path / 'tabbed.txt').read_text(encoding='utf-8')
    assert content == '  line one\n  line two\n'

    # Check compares the same post-processed staged tree against the project,
    # so a successful apply must leave nothing to report.
    run_repolish(['apply', '--check'], exit_code=0)


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Simulates Unix-style installed CLI execution from PATH.',
)
def test_post_process_runs_exactly_once_with_insertions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """post_process runs once per session even when insertions are present.

    Insertions are staged into the render tree and post-processed there, so a
    single run covers template output and insertion output alike (regression:
    insertion output used to be applied in-place to project files after the
    copy, forcing a second post_process pass over the whole project root).
    The provider also maps a plain template file so the render tree is
    non-empty — with the old in-place insertion flow both the staged and the
    project-root post_process runs fired, counting 2 invocations.
    """
    _write(
        tmp_path / 'test.txt',
        """\
        # Header
        <!-- repolish:on:tabs insert-tabs -->
        <!-- repolish:off:tabs -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def insert_tabs():
            return '\\tindented by tabs'
        return {'test.txt': {'insert-tabs': insert_tabs}}""",
        extra_methods="""\
        def create_file_mappings(self, context):
            return {'plain.txt': 'plain.txt'}
        """,
    )
    template_dir = tmp_path / 'p' / 'repolish'
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / 'plain.txt').write_text(
        '\tplain template\n',
        encoding='utf-8',
    )

    # Post-process counts invocations, then rewrites tabs as two spaces.
    script = tmp_path / 'count_and_untab.py'
    counter = tmp_path / 'invocations.txt'
    script.write_text(
        '#!/usr/bin/env python3\n'
        'import pathlib, sys\n'
        f'counter = pathlib.Path({str(counter)!r})\n'
        'count = int(counter.read_text()) if counter.exists() else 0\n'
        'counter.write_text(str(count + 1))\n'
        'for f in pathlib.Path(".").glob("*.txt"):\n'
        '    f.write_text(f.read_text().replace("\\t", "  "))\n',
        encoding='utf-8',
    )
    script.chmod(0o755)
    old_path = os.environ.get('PATH', '')
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{old_path}')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'post_process': ['count_and_untab.py'],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    run_repolish(['apply'], exit_code=0)

    # Exactly one post_process invocation for the whole session.
    assert counter.read_text(encoding='utf-8') == '1'

    # Both the mapped template and the insertion output were formatted.
    plain = (tmp_path / 'plain.txt').read_text(encoding='utf-8')
    assert plain == '  plain template\n'

    # The insertion content made it into the project file, post-processed.
    content = (tmp_path / 'test.txt').read_text(encoding='utf-8')
    assert '  indented by tabs' in content
    assert '\tindented by tabs' not in content

    # And check agrees with what apply produced.
    run_repolish(['apply', '--check'], exit_code=0)


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Simulates Unix-style installed CLI execution from PATH.',
)
def test_mapped_file_with_insertions_gets_fresh_rendered_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A destination that is both mapped and an insertion target keeps both.

    The insertion render must start from the freshly rendered template output
    (not the stale project file), and the final copy must carry the insertion
    content on top of the new template content.
    """
    # The template itself carries the insertion marker.
    template = tmp_path / 'p' / 'repolish' / 'doc.txt.jinja'
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(
        'template header\n<!-- repolish:on:extra insert-extra -->\n<!-- repolish:off:extra -->\n',
        encoding='utf-8',
    )
    (tmp_path / 'p' / 'repolish.py').write_text(
        textwrap.dedent(
            """\
            from repolish import BaseContext, Provider, BaseInputs
            from repolish.providers.models import TemplateMapping

            class Ctx(BaseContext):
                pass

            class P(Provider[Ctx, BaseInputs]):
                def create_context(self):
                    return Ctx()

                def create_file_mappings(self, context):
                    return {'doc.txt': 'doc.txt.jinja'}

                def create_file_insertions(self, context):
                    def insert_extra():
                        return 'inserted body'
                    return {'doc.txt': {'insert-extra': insert_extra}}
            """,
        ),
        encoding='utf-8',
    )

    # Stale project copy that must NOT be the base for the insertion render.
    (tmp_path / 'doc.txt').write_text(
        'stale content\n<!-- repolish:on:extra insert-extra -->\nold insertion\n<!-- repolish:off:extra -->\n',
        encoding='utf-8',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    run_repolish(['apply'], exit_code=0)

    content = (tmp_path / 'doc.txt').read_text(encoding='utf-8')
    assert 'template header' in content
    assert 'inserted body' in content
    assert 'stale content' not in content
    assert 'old insertion' not in content

    # Check agrees: the staged insertion file matches the project file.
    run_repolish(['apply', '--check'], exit_code=0)
