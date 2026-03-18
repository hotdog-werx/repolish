"""End-to-end integration tests for monorepo support."""
# ruff: noqa: ARG002  # installed_providers fixture is used for its side-effects

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .conftest import fixtures, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from .conftest import InstalledProviders


class TestStandaloneModeUnchanged:
    def test_standalone_mode_unchanged(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-monorepo repos continue to work exactly as before.

        Also checks that the debug context shows ``mode="standalone"``.
        """
        repo = fixtures.simple_repo.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply'])

        readme = repo / 'README.simple-provider.md'
        assert readme.exists()

        # Verify debug JSON records standalone mode.
        debug_files = list(
            (repo / '.repolish' / '_').glob('provider-context.*.json'),
        )
        assert debug_files, 'no provider-context debug files written'
        data = json.loads(debug_files[0].read_text())
        monorepo = data['context'].get('repolish', {}).get('monorepo', {})
        assert monorepo.get('mode') == 'standalone'


class TestMonorepoRootPass:
    def test_monorepo_root_pass_creates_root_files(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--root-only`` creates root-level files and leaves members untouched."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--root-only'])

        # Root provider output must exist.
        assert (repo / 'README.simple-provider.md').exists()

        # Member directories must NOT have been touched.
        assert not (repo / 'packages' / 'pkg-a' / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()

    def test_monorepo_root_context_is_root_mode(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Root pass debug JSON must show ``mode="root"``."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--root-only'])

        debug_files = list(
            (repo / '.repolish' / '_').glob('provider-context.*.json'),
        )
        assert debug_files
        data = json.loads(debug_files[0].read_text())
        monorepo = data['context'].get('repolish', {}).get('monorepo', {})
        assert monorepo.get('mode') == 'root'


class TestMonorepoMemberPass:
    def test_monorepo_member_pass_creates_member_files(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--member`` runs only the named member without touching root or other members."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--member', 'packages/pkg-a'])

        assert (repo / 'packages' / 'pkg-a' / 'README.simple-provider.md').exists()
        assert not (repo / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()

    def test_monorepo_member_by_name(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--member`` also accepts the package name (not just path)."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--member', 'pkg-b'])

        assert (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-a' / 'README.simple-provider.md').exists()

    def test_monorepo_unknown_member_exits_nonzero(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--member`` with an unknown name must exit with a non-zero code."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--member', 'nonexistent'], exit_code=1)


class TestMonorepoFullRun:
    def test_monorepo_full_run_all_passes(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Full ``repolish apply`` creates files at root, pkg-a, and pkg-b."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply'])

        assert (repo / 'README.simple-provider.md').exists()
        assert (repo / 'packages' / 'pkg-a' / 'README.simple-provider.md').exists()
        assert (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()
        # pkg-no-repolish must be untouched.
        assert not (repo / 'packages' / 'pkg-no-repolish' / 'README.simple-provider.md').exists()

    def test_monorepo_member_isolation(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Each member produces output with its own context_overrides (greeting)."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply'])

        content_a = (repo / 'packages' / 'pkg-a' / 'README.simple-provider.md').read_text()
        content_b = (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').read_text()

        assert 'Hello from pkg-a!' in content_a
        assert 'Hello from pkg-b!' in content_b

    def test_monorepo_local_repolish_dirs(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """.repolish/ is written at root, pkg-a, and pkg-b; no path escaping."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply'])

        assert (repo / '.repolish').is_dir()
        assert (repo / 'packages' / 'pkg-a' / '.repolish').is_dir()
        assert (repo / 'packages' / 'pkg-b' / '.repolish').is_dir()

    def test_monorepo_full_run_member_mode_in_debug(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Member debug JSON shows ``mode="package"``."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply'])

        debug_files = list(
            (repo / 'packages' / 'pkg-a' / '.repolish' / '_').glob(
                'provider-context.*.json',
            ),
        )
        assert debug_files
        data = json.loads(debug_files[0].read_text())
        monorepo = data['context'].get('repolish', {}).get('monorepo', {})
        assert monorepo.get('mode') == 'package'


class TestR10Guard:
    def test_guard_running_from_member(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Running ``repolish apply`` from inside a member exits with code 1."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        pkg_a = repo / 'packages' / 'pkg-a'
        monkeypatch.chdir(pkg_a)

        run_repolish(['apply'], exit_code=1)

    def test_standalone_flag_bypasses_guard(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--standalone`` suppresses the R10 guard and runs a single-pass apply."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        pkg_a = repo / 'packages' / 'pkg-a'
        monkeypatch.chdir(pkg_a)

        # Must succeed even though we're inside a member.
        run_repolish(['apply', '--standalone'])

        assert (pkg_a / 'README.simple-provider.md').exists()
        # Root and pkg-b must be untouched.
        assert not (repo / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()


class TestExplicitMembersConfig:
    def test_explicit_members_in_config(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``monorepo.members`` in repolish.yaml restricts which members are processed."""
        repo = fixtures.monorepo_basic.stage(tmp_path)

        # Overwrite root repolish.yaml to declare only pkg-a as a member.
        (repo / 'repolish.yaml').write_text(
            'monorepo:\n'
            '  members:\n'
            '    - packages/pkg-a\n'
            'providers:\n'
            '  simple-provider:\n'
            '    cli: simple-provider-link\n'
            '    context_overrides:\n'
            "      greeting: 'Hello from root!'\n",
            encoding='utf-8',
        )

        monkeypatch.chdir(repo)
        run_repolish(['apply'])

        assert (repo / 'packages' / 'pkg-a' / 'README.simple-provider.md').exists()
        # pkg-b is explicitly excluded.
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()
