"""Integration tests for scaffold-provider: create-only file lifecycle.

These tests replace the unit-style ``tests/integration/test_create_only.py``
with end-to-end scenarios driven through real ``repolish apply`` invocations
against fixture repos.

Scenarios covered:
- Regular template files (README.md) are always synced on apply.
- CREATE_ONLY files (SETUP.md) are seeded on first apply; subsequent
  applies never overwrite user-owned content.
- ``repolish apply --check`` reports MISSING when a create-only file has not
  been seeded yet and exits non-zero.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import fixtures, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from .conftest import InstalledProviders


def test_apply_creates_all_files_in_fresh_project(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply on a project with no prior output creates both managed files."""
    repo = fixtures.scaffold_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    _ = run_repolish(['apply'])

    assert (repo / 'README.md').exists(), 'README.md should be created by apply'
    assert (repo / 'SETUP.md').exists(), 'SETUP.md should be seeded by apply'


def test_apply_preserves_existing_init_on_reapply(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply does not overwrite a create-only file that already exists."""
    repo = fixtures.scaffold_existing_init.stage(tmp_path)
    monkeypatch.chdir(repo)

    _ = run_repolish(['apply'])

    content = (repo / 'SETUP.md').read_text(encoding='utf-8')
    assert 'must not overwrite me' in content, 'SETUP.md is create-only and must not be overwritten by apply'


def test_apply_regular_file_is_always_updated(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply overwrites a regular file (README.md) even when it already exists."""
    repo = fixtures.scaffold_existing_init.stage(tmp_path)
    (repo / 'README.md').write_text('# stale content', encoding='utf-8')
    monkeypatch.chdir(repo)

    _ = run_repolish(['apply'])

    content = (repo / 'README.md').read_text(encoding='utf-8')
    assert 'stale content' not in content, 'README.md is a regular file; apply must overwrite stale content'


def test_check_reports_missing_create_only_file(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check exits non-zero when a create-only file has not been seeded yet."""
    repo = fixtures.scaffold_fresh.stage(tmp_path)
    monkeypatch.chdir(repo)

    _ = run_repolish(['apply', '--check'], exit_code=2)


def test_check_skips_create_only_file_when_already_exists(
    installed_providers: InstalledProviders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check does not report a diff for a create-only file that already exists.

    Exercises the branch in ``comparison.py`` that adds an existing create-only
    file to the skip set so it is never compared against the template.
    """
    repo = fixtures.scaffold_existing_init.stage(tmp_path)
    monkeypatch.chdir(repo)

    # First apply: seeds README.md (regular) but must not overwrite SETUP.md
    run_repolish(['apply'])

    # Second run with --check: README.md now matches the template, SETUP.md is
    # create-only and exists, so there should be no diffs.
    _ = run_repolish(['apply', '--check'])
