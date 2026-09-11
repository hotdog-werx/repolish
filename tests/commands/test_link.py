"""Tests for the repolish link command."""

from __future__ import annotations

import os
from pathlib import Path

from repolish.cli.main import app
from repolish.cli.testing import CliRunner
from tests.conftest import init_git_repo, write_repolish_config


def _run_link(args: list[str], cwd: Path) -> str:
    """Run repolish link with given args and return output."""
    runner = CliRunner()
    old_cwd = Path.cwd()
    try:
        os.chdir(cwd)
        result = runner.invoke(app, ['link', *args])
        return result.output
    finally:
        os.chdir(old_cwd)


def _stage_static_provider(tmp_path: Path) -> None:
    """Create a minimal static provider plus repolish.yaml in *tmp_path*."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        'from repolish import BaseContext, Provider, BaseInputs\n'
        'class Ctx(BaseContext): pass\n'
        'class P(Provider[Ctx, BaseInputs]):\n'
        '    def create_context(self): return Ctx()\n',
        encoding='utf-8',
    )
    (provider_dir / 'resources').mkdir()
    (provider_dir / 'resources' / 'test.txt').write_text('content')

    write_repolish_config(
        tmp_path,
        {
            'providers': {
                'test': {
                    'provider_root': './provider',
                    'resources_dir': './provider/resources',
                },
            },
        },
    )

    init_git_repo(tmp_path)


def test_link_uses_cache_when_already_linked(tmp_path: Path) -> None:
    """A second plain `repolish link` uses cache and shows (cached) message."""
    _stage_static_provider(tmp_path)

    # First run - should link fresh
    output1 = _run_link([], tmp_path)
    assert 'are now available' in output1

    # Verify provider-info was created
    info_file = tmp_path / '.repolish' / '_' / 'provider-info.test.json'
    assert info_file.exists()

    # Second run - should use cache and show (cached) message
    output2 = _run_link([], tmp_path)
    assert '(cached)' in output2


def test_link_force_ignores_cache(tmp_path: Path) -> None:
    """`repolish link --force` re-links even when cache is valid."""
    _stage_static_provider(tmp_path)

    # First run - should link fresh
    output1 = _run_link([], tmp_path)
    assert 'are now available' in output1

    # Second run with --force - should NOT show (cached)
    output2 = _run_link(['--force'], tmp_path)
    assert '(cached)' not in output2


def test_link_marks_paused_copies_in_summary(tmp_path: Path) -> None:
    """Paused copy targets show in the summary tree and are not materialised."""
    _stage_static_provider(tmp_path)
    write_repolish_config(
        tmp_path,
        {
            'providers': {
                'test': {
                    'provider_root': './provider',
                    'resources_dir': './provider/resources',
                    'copies': [
                        {'source': 'test.txt', 'target': 'test.txt'},
                        {'source': 'test.txt', 'target': 'paused.txt'},
                    ],
                },
            },
            'paused_files': ['paused.txt'],
        },
    )

    output = _run_link([], tmp_path)

    # The summary tree marks the paused target instead of hiding it, and
    # apply_copies skips its materialisation.
    assert 'copy summary' in output
    assert '(paused)' in output
    assert (tmp_path / 'test.txt').exists()
    assert not (tmp_path / 'paused.txt').exists()


def test_link_marks_partially_paused_directory_copy(tmp_path: Path) -> None:
    """A directory copy with paused files inside shows a partial-pause marker."""
    _stage_static_provider(tmp_path)
    configs = tmp_path / 'provider' / 'resources' / 'configs'
    configs.mkdir()
    (configs / 'a.txt').write_text('a', encoding='utf-8')
    (configs / 'b.txt').write_text('b', encoding='utf-8')
    write_repolish_config(
        tmp_path,
        {
            'providers': {
                'test': {
                    'provider_root': './provider',
                    'resources_dir': './provider/resources',
                    'copies': [{'source': 'configs', 'target': 'configs'}],
                },
            },
            'paused_files': ['configs/b.txt'],
        },
    )

    output = _run_link([], tmp_path)

    # The folder itself is not paused, only one file inside it: the tree
    # marks the copy as partially paused and only that file is held back.
    assert 'copy summary' in output
    assert '(partially paused)' in output
    assert (tmp_path / 'configs' / 'a.txt').exists()
    assert not (tmp_path / 'configs' / 'b.txt').exists()
