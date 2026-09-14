"""Integration tests for the config-level post_process pipeline.

Scenarios covered:
- A plain provider file (no insertions) is formatted by post_process during
  apply, and check agrees with the result instead of reporting false drift
  (regression: the phases refactor moved the staged post-process after the
  copy into the project, so the project received unformatted content while
  check compared against the formatted staged tree)
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
