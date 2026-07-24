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


def test_link_uses_cache_when_already_linked(tmp_path: Path) -> None:
    """Second run of `repolish link` uses cache and shows (cached) message."""
    # Create a minimal static provider
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

    # Create repolish.yaml
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

    # First run - should link fresh
    output1 = _run_link([], tmp_path)
    assert '✓' in output1

    # Verify provider-info was created
    info_file = tmp_path / '.repolish' / '_' / 'provider-info.test.json'
    assert info_file.exists()

    # Second run - should use cache and show (cached) message
    output2 = _run_link([], tmp_path)
    assert '(cached)' in output2


def test_link_force_ignores_cache(tmp_path: Path) -> None:
    """`repolish link --force` re-links even when cache is valid."""
    # Create a minimal static provider
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

    # Create repolish.yaml
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

    # First run
    output1 = _run_link([], tmp_path)
    assert '✓' in output1

    # Second run with --force - should NOT show (cached)
    output2 = _run_link(['--force'], tmp_path)
    assert '(cached)' not in output2
