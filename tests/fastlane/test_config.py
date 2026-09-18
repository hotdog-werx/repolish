"""Unit tests for :func:`~repolish.fastlane.config.prepare_lane_config`.

The prepared configuration is what makes a lane run independent of
registration: the tests here exercise each alias-resolution branch and the
per-lane post_process selection without going through a CLI run (the CLI
level covers them end to end in ``test_cli.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from repolish.config.models.project import FastLanesSection
from repolish.config.models.provider import ProviderConfig
from repolish.fastlane.config import prepare_lane_config


def _stage_provider_root(tmp_path: Path, *, pkg: str = 'pkg') -> Path:
    """Create ``<tmp>/<pkg>/resources/templates`` and return the root."""
    root = tmp_path / pkg / 'resources' / 'templates'
    root.mkdir(parents=True)
    return root


def _write_config(
    project: Path,
    data: dict,
    *,
    config_name: str = 'repolish.yaml',
) -> Path:
    path = project / config_name
    path.write_text(yaml.safe_dump(data), encoding='utf-8')
    return path


class TestWithoutConfigFile:
    def test_falls_back_to_package_name(self, tmp_path: Path) -> None:
        # No repolish.yaml anywhere: the run is fully in-memory, and the
        # bookkeeping alias is the package directory name.
        provider_root = _stage_provider_root(tmp_path)
        config_path = tmp_path / 'nowhere' / 'repolish.yaml'

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias=None,
            config_path=config_path,
        )

        assert list(prepared.config.providers) == ['pkg']
        info = prepared.config.providers['pkg']
        assert info.provider_root == provider_root
        assert info.resources_dir == provider_root.parent
        assert info.symlinks == []
        assert prepared.config.paused_files == []
        assert prepared.config.post_process == []
        assert prepared.config.fast_lanes == FastLanesSection()
        assert prepared.raw_providers['pkg'].provider_root == str(provider_root)

    def test_explicit_alias_wins_even_without_config(
        self,
        tmp_path: Path,
    ) -> None:
        provider_root = _stage_provider_root(tmp_path)

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias='ghost',
            config_path=tmp_path / 'repolish.yaml',  # does not exist
        )

        assert list(prepared.config.providers) == ['ghost']
        assert prepared.config.providers['ghost'].alias == 'ghost'


class TestAliasResolution:
    def test_alias_in_config_uses_that_entry(
        self,
        tmp_path: Path,
    ) -> None:
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        config_path = _write_config(
            project,
            {
                'providers': {
                    'demo': {'provider_root': str(provider_root)},
                    'other': {'cli': 'other-link'},
                },
            },
        )

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias='demo',
            config_path=config_path,
        )

        assert list(prepared.config.providers) == ['demo']
        assert prepared.raw_providers['demo'] == ProviderConfig(
            provider_root=str(provider_root),
        )

    def test_root_match_finds_alias_for_unnamed_run(
        self,
        tmp_path: Path,
    ) -> None:
        # No explicit alias: the entry whose provider_root points at this
        # package names the run (the 'other' cli-only entry cannot match).
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        config_path = _write_config(
            project,
            {
                'providers': {
                    'other': {'cli': 'other-link'},
                    'demo': {'provider_root': str(provider_root)},
                },
            },
        )

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias=None,
            config_path=config_path,
        )

        assert list(prepared.config.providers) == ['demo']

    def test_explicit_alias_not_in_config_keeps_entry_fields(
        self,
        tmp_path: Path,
    ) -> None:
        # alias='ghost' is the provider-owned identity and does not have to
        # appear in the config; the root-matched entry still contributes its
        # per-provider fields.
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        resources = tmp_path / 'shared-resources'
        resources.mkdir()
        config_path = _write_config(
            project,
            {
                'providers': {
                    'demo': {
                        'provider_root': str(provider_root),
                        'resources_dir': str(resources),
                        'symlinks': [
                            {'source': 'configs', 'target': 'conf.d'},
                        ],
                        'overrides': {'context_merge': {'year': 2000}},
                    },
                },
            },
        )

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias='ghost',
            config_path=config_path,
        )

        info = prepared.config.providers['ghost']
        assert info.alias == 'ghost'
        assert info.resources_dir == resources
        assert [(s.source, s.target) for s in info.symlinks] == [
            (Path('configs'), Path('conf.d')),
        ]
        assert info.overrides is not None
        assert info.overrides.context_merge == {'year': 2000}
        # the raw entry is the matched one, keyed by the run alias
        assert prepared.raw_providers['ghost'].symlinks is not None

    def test_relative_provider_root_resolves_against_config_dir(
        self,
        tmp_path: Path,
    ) -> None:
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        # Same root, declared relative to the config directory.
        relative = Path('..') / 'pkg' / 'resources' / 'templates'
        config_path = _write_config(
            project,
            {'providers': {'demo': {'provider_root': relative.as_posix()}}},
        )

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias=None,
            config_path=config_path,
        )

        assert list(prepared.config.providers) == ['demo']

    def test_unlisted_provider_falls_back_to_package_name(
        self,
        tmp_path: Path,
    ) -> None:
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        config_path = _write_config(
            project,
            {'providers': {'other': {'provider_root': '/definitely/not/this'}}},
        )

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias=None,
            config_path=config_path,
        )

        assert list(prepared.config.providers) == ['pkg']
        assert prepared.raw_providers['pkg'].provider_root == str(provider_root)


class TestProjectKeys:
    def test_paused_files_and_template_overrides_carried(
        self,
        tmp_path: Path,
    ) -> None:
        # Project-wide keys apply even when this provider is not the listed
        # one: the lane run is still a run against this project.
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        config_path = _write_config(
            project,
            {
                'providers': {
                    'other': {'provider_root': '/definitely/not/this'},
                },
                'paused_files': ['plain.txt'],
                'template_overrides': {'plain.txt.jinja': None},
            },
        )

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias=None,
            config_path=config_path,
        )

        assert prepared.config.paused_files == ['plain.txt']
        assert prepared.config.template_overrides == {'plain.txt.jinja': None}

    def test_fast_lanes_section_carried(
        self,
        tmp_path: Path,
    ) -> None:
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        config_path = _write_config(
            project,
            {
                'providers': {'demo': {'provider_root': str(provider_root)}},
                'fast_lanes': {
                    'resolutions': {'plain.txt': 'fast_lane'},
                    'config': {'actions': {'post_process': ['touch lane.txt']}},
                },
            },
        )

        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias=None,
            config_path=config_path,
        )

        assert prepared.config.fast_lanes.resolutions == {
            'plain.txt': 'fast_lane',
        }
        assert 'actions' in prepared.config.fast_lanes.config


class TestPostProcessSelection:
    @pytest.fixture
    def config_path(self, tmp_path: Path) -> Path:
        provider_root = _stage_provider_root(tmp_path)
        project = tmp_path / 'project'
        project.mkdir()
        return _write_config(
            project,
            {
                'providers': {'demo': {'provider_root': str(provider_root)}},
                'post_process': ['touch project.txt'],
                'fast_lanes': {
                    'config': {'actions': {'post_process': ['touch lane.txt']}},
                },
            },
        )

    @pytest.fixture
    def provider_root(self, tmp_path: Path) -> Path:
        return tmp_path / 'pkg' / 'resources' / 'templates'

    def test_named_lane_runs_only_its_own_commands(
        self,
        provider_root: Path,
        config_path: Path,
    ) -> None:
        prepared = prepare_lane_config(
            provider_root,
            'actions',
            alias=None,
            config_path=config_path,
        )

        assert prepared.config.post_process == ['touch lane.txt']

    def test_lane_without_entry_runs_nothing(
        self,
        provider_root: Path,
        config_path: Path,
    ) -> None:
        prepared = prepare_lane_config(
            provider_root,
            'docs',
            alias=None,
            config_path=config_path,
        )

        assert prepared.config.post_process == []

    def test_all_runs_the_project_commands(
        self,
        provider_root: Path,
        config_path: Path,
    ) -> None:
        prepared = prepare_lane_config(
            provider_root,
            None,
            alias=None,
            config_path=config_path,
        )

        assert prepared.config.post_process == ['touch project.txt']
