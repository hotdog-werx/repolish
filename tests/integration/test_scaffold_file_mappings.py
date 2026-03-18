"""Integration tests for file_mappings driven through the scaffold-provider.

End-to-end scenarios (via ``repolish apply`` / ``repolish apply --check``):
- Mapped ``_repolish.*`` sources are applied to their declared destinations.
- The correct variant is selected when multiple sources are available.
- Stale mapped destinations are updated by ``repolish apply``.
- ``_repolish.*`` source files never appear verbatim in the project directory.
- ``repolish apply --check`` exits non-zero when a mapped destination is absent.
- ``repolish apply --check`` exits non-zero when a mapped destination is stale.
- ``repolish apply --check`` exits zero when every mapped destination is current.
- Nested mapped files (under ``.github/workflows/``) behave identically to
  root-level mapped files.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

from .conftest import fixtures, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from .conftest import InstalledProviders


def test_apply_variant_a(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply on a fresh variant-a project: config is written.

    prefix files are absent, and a subsequent check exits zero.
    """
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    result = run_repolish(['apply'])

    # The tables showing the mappings should not show any unknown providers
    assert 'unknown' not in result.output
    symlink_config = repo / 'symlink-config.yaml'
    assert symlink_config.exists(), 'symlink-config.yaml should be created by apply'
    assert symlink_config.is_symlink(), 'symlink-config.yaml should be a symlink'

    config = repo / 'config.yml'
    assert config.exists(), 'config.yml must be created by apply'
    assert 'option-a' in config.read_text(encoding='utf-8')
    assert not (repo / '_repolish.config-a.yml').exists()
    assert not (repo / '_repolish.config-b.yml').exists()

    run_repolish(['apply', '--check'])


def test_apply_creates_mapped_file_for_variant_b(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply with config_variant=b writes option-b content to config.yml."""
    repo = fixtures.file_mappings_variant_b_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])

    config = repo / 'config.yml'
    assert config.exists(), 'config.yml must be created by apply'
    content = config.read_text(encoding='utf-8')
    assert 'option-b' in content
    assert 'option-a' not in content


def test_apply_variant_a_stale_detected_and_restored(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check detects stale content and reports it; apply restores the file."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])
    (repo / 'config.yml').write_text('stale: content\n', encoding='utf-8')

    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'config.yml' in result.output
    assert 'stale' in result.output

    run_repolish(['apply'])
    content = (repo / 'config.yml').read_text(encoding='utf-8')
    assert 'option-a' in content, 'apply must restore variant-a content'
    assert 'stale' not in content


def test_check_exits_nonzero_when_mapped_destination_missing(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits non-zero when the mapped destination has not been created yet."""
    repo = fixtures.file_mappings_variant_a_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'MISSING' in result.output
    assert 'config.yml' in result.output


def test_check_exits_zero_when_mapped_destination_already_seeded(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits zero when the project already has the correctly-seeded config.yml."""
    repo = fixtures.file_mappings_variant_a_existing.stage(tmp_path)
    monkeypatch.chdir(repo)

    # Apply first to establish the complete state (files + symlinks), then
    # verify check exits zero — the project is already correct.
    run_repolish(['apply'])
    run_repolish(['apply', '--check'])

    # Replace the symlink with a plain file; check must detect it.
    symlink = repo / 'symlink-config.yaml'
    symlink.unlink()
    symlink.write_text('not a symlink\n', encoding='utf-8')
    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'exists but is not a symlink' in result.output

    # Corrupt the symlink so it points somewhere wrong; check must detect it.
    run_repolish(['apply'])
    symlink.unlink()
    symlink.symlink_to(repo / 'README.md')
    result = run_repolish(['apply', '--check'], exit_code=2)
    assert '(expected \\u2192' in result.output

    # Fix it; check must pass again (exercises the "correct symlink" branch).
    run_repolish(['apply'])
    run_repolish(['apply', '--check'])

    # Modify repolish.yaml to add an explicit symlinks override; this exercises
    # the collect_provider_symlinks branch that reads from config rather than
    # falling back to repolish.py defaults.
    repolish_yaml = repo / 'repolish.yaml'
    repolish_yaml.write_text(
        dedent("""\
            providers:
              scaffold-provider:
                cli: scaffold-provider-link
                context:
                  config_variant: a
                symlinks:
                  - source: configs/some-config.yaml
                    target: new-symlink-config.yaml
        """),
        encoding='utf-8',
    )
    run_repolish(['apply'])
    run_repolish(['apply', '--check'])
    assert (repo / 'new-symlink-config.yaml').exists(), 'new-symlink-config.yaml should be created by apply'


def test_apply_nested_ci(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply creates nested ci.yml, prefix sources are absent, and check passes."""
    repo = fixtures.file_mappings_nested_ci_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    run_repolish(['apply'])

    ci_file = repo / '.github' / 'workflows' / 'ci.yml'
    assert ci_file.exists(), '.github/workflows/ci.yml should be created by apply'
    assert 'name: ci' in ci_file.read_text(encoding='utf-8')
    assert not (repo / '.github' / 'workflows' / '_repolish.ci-github.yml').exists()

    run_repolish(['apply', '--check'])


def test_check_exits_nonzero_when_nested_mapped_destination_missing(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits non-zero when a nested mapped destination does not exist yet."""
    repo = fixtures.file_mappings_nested_ci_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'MISSING' in result.output
    assert '.github/workflows/ci.yml' in result.output
