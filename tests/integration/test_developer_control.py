"""Integration tests for developer control features.

Scenarios covered:
- paused_files skips a file during apply (file not written)
- paused_files skips a file during --check (no diff reported)
- template_overrides: null suppresses a file during apply
- template_overrides: null suppresses a file during --check
- template_overrides pins a file to a specific provider
- provider_root (local provider, no cli) supplies templates and is applied
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _inline_provider(directory: Path, files: dict[str, str]) -> None:
    """Create a minimal provider in ``directory`` that supplies the given files."""
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


# ---------------------------------------------------------------------------
# paused_files
# ---------------------------------------------------------------------------


@dataclass
class TCase:
    name: str
    initial_content: str
    provider_content: str
    paused: bool


def test_paused_file_is_not_written_by_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file listed in paused_files is not overwritten during apply."""
    _inline_provider(tmp_path / 'p', {'managed.txt': 'from provider\n'})
    _write(tmp_path / 'managed.txt', 'local content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'paused_files': ['managed.txt'],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'managed.txt').read_text(
        encoding='utf-8',
    ) == 'local content\n'


def test_paused_file_reports_no_diff_in_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file listed in paused_files produces no diff in --check even when content differs."""
    _inline_provider(tmp_path / 'p', {'managed.txt': 'from provider\n'})
    _write(tmp_path / 'managed.txt', 'local content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'paused_files': ['managed.txt'],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    # exit_code=0 means no diff reported
    run_repolish(['apply', '--check'], exit_code=0)


def test_unpaused_file_is_written_by_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file NOT in paused_files is updated normally by apply."""
    _inline_provider(tmp_path / 'p', {'managed.txt': 'from provider\n'})
    _write(tmp_path / 'managed.txt', 'local content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'managed.txt').read_text(
        encoding='utf-8',
    ) == 'from provider\n'


# ---------------------------------------------------------------------------
# template_overrides: null — suppress a file
# ---------------------------------------------------------------------------


def test_suppressed_file_is_not_written_by_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file suppressed via template_overrides: null is not written during apply."""
    _inline_provider(tmp_path / 'p', {'owned.txt': 'from provider\n'})

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'template_overrides': {'owned.txt': None},
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert not (tmp_path / 'owned.txt').exists()


def test_suppressed_file_reports_no_diff_in_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file suppressed via template_overrides: null produces no diff in --check."""
    _inline_provider(tmp_path / 'p', {'owned.txt': 'from provider\n'})
    # Pre-create the file with different content — check should still pass
    _write(tmp_path / 'owned.txt', 'my own content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'template_overrides': {'owned.txt': None},
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--check'], exit_code=0)


# ---------------------------------------------------------------------------
# local provider via provider_root (no cli)
# ---------------------------------------------------------------------------


def test_local_provider_root_supplies_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider configured with only provider_root applies its templates."""
    _inline_provider(tmp_path / 'local-p', {'hello.txt': 'hello from local\n'})

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'local': {'provider_root': './local-p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'hello.txt').read_text(
        encoding='utf-8',
    ) == 'hello from local\n'


def test_local_provider_without_repolish_py_applies_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider_root without repolish.py still supplies template files."""
    # No repolish.py — only a template directory
    _write(tmp_path / 'local-p' / 'repolish' / 'plain.txt', 'plain content\n')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'local': {'provider_root': './local-p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    assert (tmp_path / 'plain.txt').read_text(
        encoding='utf-8',
    ) == 'plain content\n'
