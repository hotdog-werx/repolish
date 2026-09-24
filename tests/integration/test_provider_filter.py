"""Integration tests for --providers filter option.

Tests that the --providers CLI flag correctly filters which providers run.
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


def _inline_provider(
    directory: Path,
    file_content: str,
    filename: str = 'foo.txt',
) -> None:
    """Create a minimal provider in ``directory`` that supplies a file."""
    _write(
        directory / 'repolish' / filename,
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


def _write_repolish_config(tmp_path: Path, config: dict) -> None:
    """Write repolish.yaml configuration file."""
    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(config, indent=2),
        encoding='utf-8',
    )


def test_providers_filter_runs_only_specified_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--providers flag filters to only run specified providers.

    Both p1 and p2 ship different files. With --providers p1, only p1's
    file should be created.
    """
    _inline_provider(tmp_path / 'p1', 'from p1\n', 'p1.txt')
    _inline_provider(tmp_path / 'p2', 'from p2\n', 'p2.txt')

    _write_repolish_config(
        tmp_path,
        {
            'providers_order': ['p1', 'p2'],
            'providers': {
                'p1': {'provider_root': './p1'},
                'p2': {'provider_root': './p2'},
            },
        },
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--providers', 'p1'])

    # p1's file should exist
    assert (tmp_path / 'p1.txt').read_text(encoding='utf-8') == 'from p1\n'
    # p2's file should NOT exist since p2 was filtered out
    assert not (tmp_path / 'p2.txt').exists(), 'p2.txt should not exist when filtering to p1 only'


def test_providers_filter_no_provider_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--providers flag filters to only run specified providers.

    Both p1 and p2 ship different files. With --providers p1, only p1's
    file should be created.
    """
    _inline_provider(tmp_path / 'p1', 'from p1\n', 'p1.txt')
    _inline_provider(tmp_path / 'p2', 'from p2\n', 'p2.txt')

    _write_repolish_config(
        tmp_path,
        {
            'providers': {
                'p1': {'provider_root': './p1'},
                'p2': {'provider_root': './p2'},
            },
        },
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--providers', 'p1'])

    # p1's file should exist
    assert (tmp_path / 'p1.txt').read_text(encoding='utf-8') == 'from p1\n'
    # p2's file should NOT exist since p2 was filtered out
    assert not (tmp_path / 'p2.txt').exists(), 'p2.txt should not exist when filtering to p1 only'


def test_providers_filter_multiple_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--providers with comma-separated list runs only those providers.

    Three providers ship different files. With --providers p1,p3, only
    p1 and p3's files should be created.
    """
    _inline_provider(tmp_path / 'p1', 'from p1\n', 'p1.txt')
    _inline_provider(tmp_path / 'p2', 'from p2\n', 'p2.txt')
    _inline_provider(tmp_path / 'p3', 'from p3\n', 'p3.txt')

    _write_repolish_config(
        tmp_path,
        {
            'providers_order': ['p1', 'p2', 'p3'],
            'providers': {
                'p1': {'provider_root': './p1'},
                'p2': {'provider_root': './p2'},
                'p3': {'provider_root': './p3'},
            },
        },
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--providers', 'p1,p3'])

    # p1 and p3's files should exist
    assert (tmp_path / 'p1.txt').read_text(encoding='utf-8') == 'from p1\n'
    assert (tmp_path / 'p3.txt').read_text(encoding='utf-8') == 'from p3\n'
    # p2's file should NOT exist
    assert not (tmp_path / 'p2.txt').exists(), 'p2.txt should not exist when filtering to p1,p3'


def test_providers_filter_same_destination_different_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--providers selects which provider's content wins for same destination.

    Both p1 and p2 ship foo.txt with different content. With --providers p1,
    p1's content should be applied even though p2 comes later in providers_order.
    """
    _inline_provider(tmp_path / 'p1', 'from p1\n', 'foo.txt')
    _inline_provider(tmp_path / 'p2', 'from p2\n', 'foo.txt')

    _write_repolish_config(
        tmp_path,
        {
            'providers_order': ['p1', 'p2'],
            'providers': {
                'p1': {'provider_root': './p1'},
                'p2': {'provider_root': './p2'},
            },
        },
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--providers', 'p1'])

    # p1's content should win since p2 is filtered out
    assert (tmp_path / 'foo.txt').read_text(encoding='utf-8') == 'from p1\n'


def test_no_providers_filter_runs_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --providers flag, all providers run as before.

    This ensures the filter feature doesn't break existing behavior.
    """
    _inline_provider(tmp_path / 'p1', 'from p1\n', 'p1.txt')
    _inline_provider(tmp_path / 'p2', 'from p2\n', 'p2.txt')

    _write_repolish_config(
        tmp_path,
        {
            'providers_order': ['p1', 'p2'],
            'providers': {
                'p1': {'provider_root': './p1'},
                'p2': {'provider_root': './p2'},
            },
        },
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    # Both files should exist since no filter was applied
    assert (tmp_path / 'p1.txt').read_text(encoding='utf-8') == 'from p1\n'
    assert (tmp_path / 'p2.txt').read_text(encoding='utf-8') == 'from p2\n'
