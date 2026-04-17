"""Integration tests for multi-provider ordering and template_overrides.

Scenarios covered:
- When multiple providers supply the same file, the later provider in
  ``providers_order`` wins by default.
- ``template_overrides`` pins a destination file to a specific provider,
  overriding the default last-wins rule.
"""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _inline_provider(directory: Path, file_content: str) -> None:
    """Create a minimal provider in ``directory`` that supplies ``foo.txt``."""
    _write(
        directory / 'repolish' / 'foo.txt',
        file_content,
    )
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


def test_later_provider_takes_precedence_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without template_overrides the last provider in providers_order wins.

    Both p1 and p2 ship ``foo.txt``.  With p2 listed last, its content is
    applied unless overridden.
    """
    _inline_provider(tmp_path / 'p1', 'from p1\n')
    _inline_provider(tmp_path / 'p2', 'from p2\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers_order': ['p1', 'p2'],
                'providers': {
                    'p1': {'provider_root': './p1'},
                    'p2': {'provider_root': './p2'},
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'foo.txt').read_text(encoding='utf-8') == 'from p2\n'


def test_template_overrides_pin_file_to_earlier_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """template_overrides pins foo.txt to p1 even though p2 comes later.

    Without the override p2 would win; the override forces p1's content to be
    applied regardless of provider order.
    """
    _inline_provider(tmp_path / 'p1', 'from p1\n')
    _inline_provider(tmp_path / 'p2', 'from p2\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers_order': ['p1', 'p2'],
                'providers': {
                    'p1': {'provider_root': './p1'},
                    'p2': {'provider_root': './p2'},
                },
                'template_overrides': {'foo.txt': 'p1'},
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'foo.txt').read_text(encoding='utf-8') == 'from p1\n'
