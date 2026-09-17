"""Tests for the generated provider CLI: ``provider_cli`` and ``run_lane``.

A fixture provider package (modeled on the github-actions example from the
fast lanes design) is staged on disk with real ``repolish.yaml`` project
configs, so these cover the production path: config discovery, alias
resolution, the single-provider pipeline with the dry pass skipped, and the
parity guarantee against a full ``repolish apply``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest
import yaml

from repolish.cli.testing import CliRunner
from repolish.commands.apply.options import ApplyOptions
from repolish.commands.apply.session import run_session
from repolish.exceptions import ConfigValidationError
from repolish.fastlane import provider_cli
from tests.testing.test_e2e import _make_provider_pkg

if TYPE_CHECKING:
    from pathlib import Path

    import cyclopts

runner = CliRunner()

LaneCli = tuple['cyclopts.App', 'Path', type]
"""The lane_cli fixture tuple: (app, staged project dir, provider class)."""

_LANE_PROVIDER = """\
    from repolish import BaseContext, BaseInputs, FastLaneSpec, Provider, TemplateMapping

    class Ctx(BaseContext):
        pass


    def _usage():
        return 'usage: demo-cli actions'


    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()

        def create_file_mappings(self, context):
            return {'.github/workflows/ci.yml': 'ci.yml.jinja'}

        def create_fast_lanes(self):
            return {
                'actions': FastLaneSpec(
                    file_mappings={
                        'action1/action.yaml': TemplateMapping(
                            '_repolish.action.yaml.jinja',
                            extra_context={'module': 'action1.main'},
                        ),
                        'plain.txt': 'plain.txt.jinja',
                    },
                ),
                'docs': FastLaneSpec(
                    file_insertions={'README.md': {'render-usage': _usage}},
                ),
            }
    """

_TEMPLATES = {
    'ci.yml.jinja': 'name: CI\n',
    '_repolish.action.yaml.jinja': 'runs: uvx --from {{ module }}\n',
    'plain.txt.jinja': 'plain output\n',
}


def _stage_project(
    provider_cls: type,
    base: Path,
    *,
    extra_config: dict | None = None,
    alias: str = 'demo',
) -> Path:
    """Write a project dir whose repolish.yaml registers *provider_cls*."""
    provider_root = base / 'pkg' / 'resources' / 'templates'
    project = base / 'project'
    project.mkdir()
    (project / 'README.md').write_text(
        'intro\n\n<!-- repolish:on:usage render-usage -->\n<!-- repolish:off:usage -->\n',
        encoding='utf-8',
    )
    config_data = {
        'providers': {alias: {'provider_root': str(provider_root)}},
        **(extra_config or {}),
    }
    (project / 'repolish.yaml').write_text(
        yaml.safe_dump(config_data),
        encoding='utf-8',
    )
    return project


@pytest.fixture
def lane_cli(tmp_path: Path):
    """A provider with two lanes plus its generated CLI and staged project."""
    provider_cls = _make_provider_pkg(
        tmp_path,
        _LANE_PROVIDER,
        templates=_TEMPLATES,
    )
    app = provider_cli(provider_cls)
    project = _stage_project(provider_cls, tmp_path)
    return app, project, provider_cls


class TestSubcommands:
    def test_subcommands_come_from_create_fast_lanes(
        self,
        lane_cli: LaneCli,
    ) -> None:
        app, _, _ = lane_cli

        result = runner.invoke(app, ['--help'])

        assert result.exit_code == 0
        for name in ('actions', 'docs', 'all'):
            assert name in result.output

    def test_lane_subcommand_runs_only_lane_contributions(
        self,
        lane_cli: LaneCli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app, project, _ = lane_cli
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['actions'])

        assert result.exit_code == 0, result.output
        assert (project / 'action1' / 'action.yaml').read_text(
            encoding='utf-8',
        ) == ('runs: uvx --from action1.main\n')
        # regular-hook mapping did not run
        assert not (project / '.github' / 'workflows' / 'ci.yml').exists()
        # docs-lane insertion did not run
        assert 'usage: demo-cli actions' not in (project / 'README.md').read_text(encoding='utf-8')

    def test_all_subcommand_merges_lanes_and_regular(
        self,
        lane_cli: LaneCli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app, project, _ = lane_cli
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['all'])

        assert result.exit_code == 0, result.output
        assert (project / 'action1' / 'action.yaml').exists()
        assert (project / '.github' / 'workflows' / 'ci.yml').exists()
        assert 'usage: demo-cli actions' in (project / 'README.md').read_text(
            encoding='utf-8',
        )

    def test_docs_lane_runs_only_insertions(
        self,
        lane_cli: LaneCli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app, project, _ = lane_cli
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['docs'])

        assert result.exit_code == 0, result.output
        readme = (project / 'README.md').read_text(encoding='utf-8')
        assert 'usage: demo-cli actions' in readme
        assert not (project / 'action1' / 'action.yaml').exists()


class TestConfigHandling:
    def test_paused_files_from_real_config_are_honored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider_cls = _make_provider_pkg(
            tmp_path,
            _LANE_PROVIDER,
            templates=_TEMPLATES,
        )
        app = provider_cli(provider_cls)
        project = _stage_project(
            provider_cls,
            tmp_path,
            extra_config={'paused_files': ['plain.txt']},
        )
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['actions'])

        assert result.exit_code == 0, result.output
        assert not (project / 'plain.txt').exists()
        assert (project / 'action1' / 'action.yaml').exists()

    def test_check_flag_compares_without_writing(
        self,
        lane_cli: LaneCli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app, project, _ = lane_cli
        monkeypatch.chdir(project)

        missing = runner.invoke(app, ['actions', '--check'])
        assert missing.exit_code == 2, missing.output
        assert not (project / 'action1' / 'action.yaml').exists()

        runner.invoke(app, ['actions'])
        clean = runner.invoke(app, ['actions', '--check'])
        assert clean.exit_code == 0, clean.output

    def test_missing_config_file_errors_clearly(
        self,
        lane_cli: LaneCli,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app, _, _ = lane_cli
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ['actions'])

        assert result.exit_code != 0
        assert isinstance(result.exception, ConfigValidationError)

    def test_unregistered_provider_errors_with_link_hint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider_cls = _make_provider_pkg(
            tmp_path,
            _LANE_PROVIDER,
            templates=_TEMPLATES,
        )
        app = provider_cli(provider_cls)
        project = tmp_path / 'project'
        project.mkdir()
        # The config resolves (some other provider is registered) but no
        # entry points at this CLI's package, so alias resolution must say so.
        (project / 'repolish.yaml').write_text(
            'providers:\n  other:\n    provider_root: /definitely/not/this\n',
            encoding='utf-8',
        )
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['actions'])

        assert result.exit_code != 0
        exc = result.exception
        assert isinstance(exc, ConfigValidationError)
        assert 'repolish link' in str(exc)


class TestAliasResolution:
    def test_alias_resolved_by_provider_root_match(
        self,
        lane_cli: LaneCli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The staged config registers the provider under 'demo' with its
        # resources/templates path; the CLI must find that alias on its own.
        app, project, _ = lane_cli
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['actions'])

        assert result.exit_code == 0, result.output

    def test_alias_override_wins(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider_cls = _make_provider_pkg(
            tmp_path,
            _LANE_PROVIDER,
            templates=_TEMPLATES,
        )
        app = provider_cli(provider_cls, alias='renamed')
        project = _stage_project(provider_cls, tmp_path, alias='renamed')
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['actions'])

        assert result.exit_code == 0, result.output
        assert (project / 'action1' / 'action.yaml').exists()

    def test_alias_override_rejects_unknown_alias(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider_cls = _make_provider_pkg(
            tmp_path,
            _LANE_PROVIDER,
            templates=_TEMPLATES,
        )
        app = provider_cli(provider_cls, alias='ghost')
        project = _stage_project(provider_cls, tmp_path)  # registered as 'demo'
        monkeypatch.chdir(project)

        result = runner.invoke(app, ['actions'])

        assert result.exit_code != 0
        assert isinstance(result.exception, ConfigValidationError)


class TestProviderRootDiscovery:
    def test_provider_without_templates_dir_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A provider package with a pyproject.toml but no resources/templates:
        # the walk must stop at the package root and say what is missing.
        pkg = tmp_path / 'rootless'
        pkg.mkdir()
        (pkg / 'pyproject.toml').write_text('[project]\n', encoding='utf-8')
        (pkg / 'mod.py').write_text(
            'from repolish import Provider\n\n\nclass Rootless(Provider):\n    pass\n',
            encoding='utf-8',
        )
        monkeypatch.syspath_prepend(tmp_path)
        mod = importlib.import_module('rootless.mod')

        with pytest.raises(RuntimeError, match='resources/templates'):
            provider_cli(mod.Rootless)


class TestParamParity:
    def test_lane_subcommands_expose_the_apply_flags(
        self,
        lane_cli: LaneCli,
    ) -> None:
        """Lane params derive from the apply CLI's model, so flags cannot drift."""
        app, _, _ = lane_cli

        result = runner.invoke(app, ['actions', '--help'])

        assert result.exit_code == 0, result.output
        for flag in (
            '--config',
            '--check',
            '--skip-post-process',
            '--fail-on-warnings',
        ):
            assert flag in result.output

    def test_skip_post_process_flag_is_honored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider_cls = _make_provider_pkg(
            tmp_path,
            _LANE_PROVIDER,
            templates=_TEMPLATES,
        )
        app = provider_cli(provider_cls)
        project = _stage_project(
            provider_cls,
            tmp_path,
            extra_config={'post_process': ['touch post.txt']},
        )
        monkeypatch.chdir(project)

        skipped = runner.invoke(app, ['actions', '--skip-post-process'])
        assert skipped.exit_code == 0, skipped.output
        assert not (project / 'post.txt').exists()

        applied = runner.invoke(app, ['actions'])
        assert applied.exit_code == 0, applied.output
        assert (project / 'post.txt').exists()


class TestParity:
    def test_lane_output_matches_full_apply_check(
        self,
        lane_cli: LaneCli,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The parity guarantee: a lane run then a full apply check has no drift."""
        app, project, _ = lane_cli
        monkeypatch.chdir(project)

        lane_run = runner.invoke(app, ['all'])
        assert lane_run.exit_code == 0, lane_run.output

        rc = run_session(
            ApplyOptions(
                config_path=project / 'repolish.yaml',
                check_only=True,
            ),
        )
        assert rc == 0
