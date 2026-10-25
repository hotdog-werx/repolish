"""Tests for the repolish link command."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repolish.cli.main import app
from repolish.cli.testing import CliRunner, Result
from repolish.commands.link import _linked_path
from repolish.config.models.metadata import ProviderFileInfo
from repolish.linker.providers import write_provider_info_file
from tests.conftest import init_git_repo, write_repolish_config


def test_linked_path_falls_back_to_the_recorded_path(tmp_path: Path) -> None:
    """A recorded resources dir outside the repo displays as its absolute path.

    The recorded path is tried as-is and then resolved before giving up (a
    module provider's `.repolish/` entry is a symlink into its package), so
    only a directory that is truly outside the config dir reaches the
    absolute-path fallback.
    """
    config_dir = tmp_path / 'proj'
    config_dir.mkdir()
    outside = tmp_path / 'elsewhere' / 'resources'
    outside.mkdir(parents=True)
    write_provider_info_file(
        'odd',
        ProviderFileInfo(resources_dir=str(outside)),
        config_dir,
    )
    assert _linked_path('odd', config_dir) == str(outside)


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

    # First run - should link fresh, naming the directory actually linked
    output1 = _run_link([], tmp_path)
    assert '- provider/resources from test are now available' in output1

    # Verify provider-info was created
    info_file = tmp_path / '.repolish' / '_' / 'provider-info.test.json'
    assert info_file.exists()

    # Second run - should use cache, still naming the linked directory
    output2 = _run_link([], tmp_path)
    assert '- provider/resources from test (cached)' in output2


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


def _run_link_result(args: list[str], cwd: Path) -> Result:
    """Run repolish link and return the full Result (exit code included)."""
    runner = CliRunner()
    old_cwd = Path.cwd()
    try:
        os.chdir(cwd)
        return runner.invoke(app, ['link', *args])
    finally:
        os.chdir(old_cwd)


def _stage_two_static_providers(tmp_path: Path) -> None:
    """Create two static providers (test, other) plus repolish.yaml."""
    for name in ('test', 'other'):
        provider_dir = tmp_path / f'{name}-provider'
        provider_dir.mkdir()
        (provider_dir / 'repolish.py').write_text(
            'from repolish import BaseContext, Provider, BaseInputs\n'
            'class Ctx(BaseContext): pass\n'
            'class P(Provider[Ctx, BaseInputs]):\n'
            '    def create_context(self): return Ctx()\n',
            encoding='utf-8',
        )
        (provider_dir / 'resources').mkdir()
        (provider_dir / 'resources' / f'{name}.txt').write_text(name)

    write_repolish_config(
        tmp_path,
        {
            'providers': {
                'test': {
                    'provider_root': './test-provider',
                    'resources_dir': './test-provider/resources',
                },
                'other': {
                    'provider_root': './other-provider',
                    'resources_dir': './other-provider/resources',
                },
            },
        },
    )

    init_git_repo(tmp_path)


def test_link_single_alias_registers_only_that_provider(tmp_path: Path) -> None:
    """`repolish link test` registers only the aliased provider."""
    _stage_two_static_providers(tmp_path)

    output = _run_link(['test'], tmp_path)

    assert 'from test' in output
    info = tmp_path / '.repolish' / '_' / 'provider-info.test.json'
    other_info = tmp_path / '.repolish' / '_' / 'provider-info.other.json'
    assert info.exists()
    assert not other_info.exists()


def test_link_unknown_alias_lists_valid_aliases(tmp_path: Path) -> None:
    """An unknown alias fails with the configured aliases listed."""
    _stage_two_static_providers(tmp_path)

    result = _run_link_result(['missing'], tmp_path)

    assert result.exit_code == 1
    assert 'unknown provider alias' in result.output
    assert 'test' in result.output
    assert 'other' in result.output


def test_link_register_only_leaves_copies_unmaterialised(
    tmp_path: Path,
) -> None:
    """`repolish link --register-only` registers but skips the copy phase."""
    _stage_static_provider(tmp_path)
    write_repolish_config(
        tmp_path,
        {
            'providers': {
                'test': {
                    'provider_root': './provider',
                    'resources_dir': './provider/resources',
                    'copies': [{'source': 'test.txt', 'target': 'test.txt'}],
                },
            },
        },
    )

    result = _run_link_result(['--register-only'], tmp_path)

    assert result.exit_code == 0
    assert (tmp_path / '.repolish' / '_' / 'provider-info.test.json').exists()
    assert not (tmp_path / 'test.txt').exists()


@pytest.fixture
def cli_module_pkg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """An importable mylib_ws package with the default resources layout."""
    pkg_parent = tmp_path / 'pkgroot'
    pkg_root = pkg_parent / 'mylib_ws'
    pkg_root.mkdir(parents=True)
    (pkg_root / '__init__.py').write_text('')
    resources = pkg_root / 'resources'
    templates = resources / 'templates'
    templates.mkdir(parents=True)
    (templates / 'repolish.py').write_text('')
    monkeypatch.syspath_prepend(str(pkg_parent))
    return pkg_root


def test_link_one_off_binds_alias_and_module(
    tmp_path: Path,
    cli_module_pkg: Path,
) -> None:
    """`repolish link <alias> <module> --no-config` links without a config file."""
    result = _run_link_result(
        ['ad-hoc', 'mylib_ws', '--no-config'],
        tmp_path,
    )

    assert result.exit_code == 0
    assert (tmp_path / '.repolish' / 'mylib-ws').exists()
    assert (tmp_path / '.repolish' / '_' / 'provider-info.ad-hoc.json').exists()


def test_link_no_config_without_pair_is_rejected(tmp_path: Path) -> None:
    """`repolish link --no-config` alone has nothing linkable."""
    _stage_static_provider(tmp_path)

    result = _run_link_result(['--no-config'], tmp_path)

    assert result.exit_code == 1
    assert '--no-config requires an ALIAS and MODULE pair' in result.output
