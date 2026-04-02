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
        monorepo = data['context'].get('repolish', {}).get('workspace', {})
        assert monorepo.get('mode') == 'standalone'


class TestMonorepoRootPass:
    def test_monorepo_root_pass_suppresses_auto_staging(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--root-only`` runs cleanly but auto-staged files are suppressed.

        Root-pass providers must use explicit ``create_file_mappings`` to write
        files; auto-staging is intentionally disabled for root passes so that
        providers designed for member repos don't litter the monorepo root.
        """
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--root-only'])

        # Auto-staged file from simple-provider must NOT appear at root.
        assert not (repo / 'README.simple-provider.md').exists()

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
        monorepo = data['context'].get('repolish', {}).get('workspace', {})
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

        # Root pass suppresses auto-staging; only member files appear.
        assert not (repo / 'README.simple-provider.md').exists()
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
        """Member debug JSON shows ``mode="member"``."""
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
        monorepo = data['context'].get('repolish', {}).get('workspace', {})
        assert monorepo.get('mode') == 'member'


class TestR10Guard:
    def test_running_from_member_applies_standalone_with_note(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Running from inside a member succeeds (standalone) and prints a note."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        pkg_a = repo / 'packages' / 'pkg-a'
        monkeypatch.chdir(pkg_a)

        result = run_repolish(['apply'])

        # Member's own files must be applied.
        assert (pkg_a / 'README.simple-provider.md').exists()
        # Root and other members must be untouched.
        assert not (repo / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()
        # An informational note (not an error) must appear.
        assert 'note:' in result.output
        assert 'root pass skipped' in result.output

    def test_standalone_flag_suppresses_note(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--standalone`` runs a single-pass apply without printing the member note."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        pkg_a = repo / 'packages' / 'pkg-a'
        monkeypatch.chdir(pkg_a)

        result = run_repolish(['apply', '--standalone'])

        assert (pkg_a / 'README.simple-provider.md').exists()
        # Root and pkg-b must be untouched.
        assert not (repo / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()
        assert 'note:' not in result.output


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
            'workspace:\n'
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


class TestDevkitProviderCommunication:
    def test_root_file_receives_messages_from_all_member_providers(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Member providers communicate up to the root via WorkspaceProviderInputs.

        The fixture has two members (pkg-alpha and pkg-beta), each running
        devkit-python and devkit-workspace.  Both providers emit a
        ``WorkspaceProviderInputs`` with ``add_to_root`` set.  The root
        WorkspaceProvider collects all of these in ``finalize_context`` and
        writes ``root_file.md`` via an explicit ``create_file_mappings`` entry.

        Expected: 4 provider messages in the file (2 members x 2 providers).
        """
        repo = fixtures.monorepo_devkit.stage(tmp_path)
        monkeypatch.chdir(repo)

        _ = run_repolish(['apply'])
        root_file = repo / 'root_file.md'
        assert root_file.exists(), 'root_file.md was not created by the workspace provider'

        content = root_file.read_text()
        # Collect provider message lines only (contain ': ', not section headers).
        messages = [
            line for line in content.splitlines() if line.strip() and not line.startswith('#') and ': ' in line
        ]

        # Every member provider emits one message → 2 members x 2 providers = 4.
        assert len(messages) == 4, f'expected 4 provider messages, got {len(messages)}: {messages}'

        # Both pkg-alpha and pkg-beta must have contributed a python: message.
        pkg_alpha_msg = [m for m in messages if 'python:' in m and 'pkg-alpha' in m]
        pkg_beta_msg = [m for m in messages if 'python:' in m and 'pkg-beta' in m]
        assert pkg_alpha_msg, 'no python: message from pkg-alpha'
        assert pkg_beta_msg, 'no python: message from pkg-beta'

        # Both members' workspace provider messages must also appear.
        workspace_msgs = [m for m in messages if 'workspace:' in m]
        assert len(workspace_msgs) == 2, f'expected 2 workspace: messages (one per member), got {len(workspace_msgs)}'

    def test_member_path_field_exposes_member_path(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """member_path on the input payload resolves sources for every received input.

        The WorkspaceProvider's provide_inputs sets member_path from
        opt.own_context.repolish.provider.session.member_path, so finalize_context
        at the root can read inp.member_path directly without any lookup.

        Both pkg-alpha and pkg-beta emit inputs (2 per member via devkit-python
        and devkit-workspace), so after de-duplication the sources section must
        contain exactly those two repo-relative paths.
        """
        repo = fixtures.monorepo_devkit.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply'])
        root_file = repo / 'root_file.md'
        assert root_file.exists()

        content = root_file.read_text()
        assert '# Sources' in content, 'sources section not rendered'

        source_lines = []
        in_sources = False
        for line in content.splitlines():
            if line.strip() == '# Sources':
                in_sources = True
                continue
            if in_sources and line.startswith('#'):
                break
            if in_sources and line.strip():
                source_lines.append(line.strip())

        assert sorted(source_lines) == [
            'packages/pkg-alpha',
            'packages/pkg-beta',
        ], f'expected member paths in sources, got: {source_lines}'
