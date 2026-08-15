"""End-to-end integration tests for monorepo support."""
# installed_providers fixture is used for its side-effects

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
    def test_monorepo_root_pass(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--root-only`` runs cleanly with correct mode and suppressed auto-staging.

        Root-pass providers must use explicit ``create_file_mappings`` to write
        files; auto-staging is intentionally disabled for root passes so that
        providers designed for member repos don't litter the monorepo root.

        Also verifies that debug JSON shows ``mode="root"``.
        """
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--root-only'])

        # Auto-staged file from simple-provider must NOT appear at root.
        assert not (repo / 'README.simple-provider.md').exists()

        # Member directories must NOT have been touched.
        assert not (repo / 'packages' / 'pkg-a' / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()

        # Verify debug JSON shows root mode
        debug_files = list(
            (repo / '.repolish' / '_').glob('provider-context.*.json'),
        )
        assert debug_files
        data = json.loads(debug_files[0].read_text())
        monorepo = data['context'].get('repolish', {}).get('workspace', {})
        assert monorepo.get('mode') == 'root'


class TestMonorepoValidatorDispatch:
    def test_monorepo_root_mode_calls_validators(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A root-mode handler can register a validator during a monorepo root pass."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        (repo / 'README.root-validated.md').write_text(
            '# Root validation target\n',
            encoding='utf-8',
        )

        provider_dir = repo / 'demo-validator-provider'
        provider_dir.mkdir()
        (provider_dir / 'repolish' / 'config.toml').parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        (provider_dir / 'repolish' / 'config.toml').write_text(
            'name = "demo-validator"\n',
            encoding='utf-8',
        )
        (provider_dir / 'repolish.py').write_text(
            """
from pathlib import Path

from repolish import BaseContext, BaseInputs, ModeHandler, Provider
from repolish.providers.models import ValidationResult


class Ctx(BaseContext):
    pass


class RootHandler(ModeHandler[Ctx, BaseInputs]):
    def create_file_validators(self, ctx):
        def lint(context, path: Path):
            text = path.read_text(encoding='utf-8')
            return ValidationResult(
                status='pass' if '# Root validation target' in text else 'error',
                message='root validator ok',
                path=str(path),
                validator_name='lint',
            )

        return {'README.root-validated.md': {'lint': lint}}


class DemoProvider(Provider[Ctx, BaseInputs]):
    root_mode = RootHandler

    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        return {}
""",
            encoding='utf-8',
        )

        (repo / 'repolish.yaml').write_text(
            json.dumps(
                {
                    'providers': {
                        'demo-validator-provider': {
                            'provider_root': './demo-validator-provider',
                        },
                    },
                },
            ),
            encoding='utf-8',
        )

        monkeypatch.chdir(repo)
        result = run_repolish(['apply', '--root-only'])
        assert (repo / 'README.root-validated.md').exists()
        assert 'README.root-validated.md' in result.output
        assert 'no file in stage' in result.output
        assert '✓ lint' in result.output
        assert 'config.toml' in result.output
        assert 'not in create_file_mappings (root mode)' in result.output

    def test_monorepo_root_validator_stays_with_owning_provider_for_workspace_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A validator for a workspace-owned root file is attributed to the validator provider."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        (repo / 'workspace-provider').mkdir()
        (repo / 'workspace-provider' / 'repolish').mkdir(parents=True)
        (repo / 'workspace-provider' / 'repolish' / 'config.toml').write_text(
            'name = "workspace"\n',
        )
        (repo / 'workspace-provider' / 'repolish' / '.gitignore.jinja').write_text(
            'node_modules/\n',
            encoding='utf-8',
        )
        (repo / 'workspace-provider' / 'repolish.py').write_text(
            """
from repolish import BaseContext, BaseInputs, Provider

class Ctx(BaseContext):
    pass

class WorkspaceProvider(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        return {'.gitignore': '.gitignore.jinja'}
""",
            encoding='utf-8',
        )

        (repo / 'demo-github').mkdir()
        (repo / 'demo-github' / 'repolish').mkdir(parents=True)
        (repo / 'demo-github' / 'repolish' / 'config.toml').write_text(
            'name = "demo-github"\n',
        )
        (repo / 'demo-github' / 'repolish.py').write_text(
            """
from pathlib import Path

from repolish import BaseContext, BaseInputs, Provider
from repolish.providers.models import ValidationResult

class Ctx(BaseContext):
    pass

class GitHubProvider(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        return {}

    def create_file_validators(self, ctx):
        def lint(context, path: Path):
            text = path.read_text(encoding='utf-8')
            return ValidationResult(
                status='pass' if 'node_modules/' in text else 'error',
                message='missing dependency ignore rule',
                path=str(path),
                validator_name='lint',
            )

        return {'.gitignore': {'lint': lint}}
""",
            encoding='utf-8',
        )

        (repo / 'repolish.yaml').write_text(
            json.dumps(
                {
                    'providers': {
                        'workspace-provider': {
                            'provider_root': './workspace-provider',
                        },
                        'demo-github': {'provider_root': './demo-github'},
                    },
                },
            ),
            encoding='utf-8',
        )

        monkeypatch.chdir(repo)
        result = run_repolish(['apply'])
        assert (repo / '.gitignore').exists()
        assert 'workspace-provider' in result.output
        assert 'demo-github' in result.output
        assert 'lint' in result.output

    def test_monorepo_root_validator_failure_exits_nonzero_in_strict_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failing root validator on a workspace-owned file still aborts in strict mode."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        (repo / 'workspace-provider').mkdir()
        (repo / 'workspace-provider' / 'repolish').mkdir(parents=True)
        (repo / 'workspace-provider' / 'repolish' / 'config.toml').write_text(
            'name = "workspace"\n',
        )
        (repo / 'workspace-provider' / 'repolish' / '.gitignore.jinja').write_text(
            '# generated\n',
            encoding='utf-8',
        )
        (repo / 'workspace-provider' / 'repolish.py').write_text(
            """
from repolish import BaseContext, BaseInputs, Provider

class Ctx(BaseContext):
    pass

class WorkspaceProvider(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        return {'.gitignore': '.gitignore.jinja'}
""",
            encoding='utf-8',
        )

        (repo / 'demo-github').mkdir()
        (repo / 'demo-github' / 'repolish').mkdir(parents=True)
        (repo / 'demo-github' / 'repolish' / 'config.toml').write_text(
            'name = "demo-github"\n',
        )
        (repo / 'demo-github' / 'repolish.py').write_text(
            """
from pathlib import Path

from repolish import BaseContext, BaseInputs, Provider
from repolish.providers.models import ValidationResult

class Ctx(BaseContext):
    pass

class GitHubProvider(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        return {}

    def create_file_validators(self, ctx):
        def lint(context, path: Path):
            return ValidationResult(
                status='error',
                message='gitignore missing required rule',
                path=str(path),
                validator_name='lint',
            )

        return {'.gitignore': {'lint': lint}}
""",
            encoding='utf-8',
        )

        (repo / 'repolish.yaml').write_text(
            json.dumps(
                {
                    'providers': {
                        'workspace-provider': {
                            'provider_root': './workspace-provider',
                        },
                        'demo-github': {'provider_root': './demo-github'},
                    },
                },
            ),
            encoding='utf-8',
        )

        monkeypatch.chdir(repo)
        result = run_repolish(['apply', '--strict'], exit_code=1)
        assert (repo / '.gitignore').exists()
        assert 'demo-github@' in result.output
        assert 'lint' in result.output
        assert 'gitignore missing required rule' in result.output
        assert 'error' in result.output.lower()


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
    def test_monorepo_full_run(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Full ``repolish apply`` creates member files with correct context and debug info.

        Verifies:
        - Files created at member directories (pkg-a, pkg-b), not at root or pkg-no-repolish
        - Each member's context_overrides applied (greeting message)
        - .repolish/ directories created at root and each member
        - Debug JSON shows mode="member" for member passes
        """
        repo = fixtures.monorepo_basic.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply'])

        # Files created at members, not at root or pkg-no-repolish
        assert not (repo / 'README.simple-provider.md').exists()
        readme_a = repo / 'packages' / 'pkg-a' / 'README.simple-provider.md'
        readme_b = repo / 'packages' / 'pkg-b' / 'README.simple-provider.md'
        assert readme_a.exists()
        assert readme_b.exists()
        assert not (repo / 'packages' / 'pkg-no-repolish' / 'README.simple-provider.md').exists()

        # Each member's context_overrides applied
        assert 'Hello from pkg-a!' in readme_a.read_text()
        assert 'Hello from pkg-b!' in readme_b.read_text()

        # .repolish/ directories created
        assert (repo / '.repolish').is_dir()
        assert (repo / 'packages' / 'pkg-a' / '.repolish').is_dir()
        assert (repo / 'packages' / 'pkg-b' / '.repolish').is_dir()

        # Debug JSON shows member mode
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
    def test_r10_guard_behavior(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Running from inside a member shows note; --standalone suppresses it."""
        repo = fixtures.monorepo_basic.stage(tmp_path)
        pkg_a = repo / 'packages' / 'pkg-a'
        monkeypatch.chdir(pkg_a)

        # Without --standalone: note should appear
        result_default = run_repolish(['apply'])
        assert (pkg_a / 'README.simple-provider.md').exists()
        assert not (repo / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()
        assert 'note:' in result_default.output
        assert 'root pass skipped' in result_default.output

        # Clean up for second run
        (pkg_a / 'README.simple-provider.md').unlink()

        # With --standalone: note should NOT appear
        result_standalone = run_repolish(['apply', '--standalone'])
        assert (pkg_a / 'README.simple-provider.md').exists()
        assert not (repo / 'README.simple-provider.md').exists()
        assert not (repo / 'packages' / 'pkg-b' / 'README.simple-provider.md').exists()
        assert 'note:' not in result_standalone.output


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
            '    overrides:\n'
            '      context_dotted:\n'
            "        greeting: 'Hello from root!'\n",
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


class TestPromoteFileMappings:
    """Integration tests for promote_file_mappings — promoting files from members to root."""

    def test_promoted_files_behavior(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Promoted files appear at root, not in member dirs; --check validates state."""
        repo = fixtures.monorepo_devkit.stage(tmp_path)
        monkeypatch.chdir(repo)

        # First verify --check fails before apply (promoted files missing)
        run_repolish(['apply', '--check'], exit_code=2)

        # Apply should create promoted files at root
        run_repolish(['apply'])

        alpha_workflow = repo / '.github' / 'workflows' / '_ci-checks_pkg-alpha.yaml'
        beta_workflow = repo / '.github' / 'workflows' / '_ci-checks_pkg-beta.yaml'

        assert alpha_workflow.exists()
        assert beta_workflow.exists()
        assert 'pkg-alpha' in alpha_workflow.read_text()
        assert 'pkg-beta' in beta_workflow.read_text()

        # Promoted files must NOT appear in member dirs
        for pkg in ('pkg-alpha', 'pkg-beta'):
            member_dir = repo / 'packages' / pkg
            leaked = list(member_dir.rglob('_ci-checks*.yaml'))
            assert not leaked, f'promoted template leaked into member dir {pkg}'

        # --check should now pass
        run_repolish(['apply', '--check'], exit_code=0)

    def test_root_only_skips_promotion_pass(
        self,
        installed_providers: InstalledProviders,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--root-only`` must not run the promotion pass (no member sessions applied)."""
        repo = fixtures.monorepo_devkit.stage(tmp_path)
        monkeypatch.chdir(repo)

        run_repolish(['apply', '--root-only'])

        # Promoted files must not appear — the promotion pass is skipped for --root-only.
        alpha_workflow = repo / '.github' / 'workflows' / '_ci-checks_pkg-alpha.yaml'
        assert not alpha_workflow.exists(), 'promoted file appeared despite --root-only'
