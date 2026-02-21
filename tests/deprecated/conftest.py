import json
from pathlib import Path
from textwrap import dedent
from typing import Protocol

import pytest
import yaml

from repolish.utils import open_utf8


class YamlConfigFileFixture(Protocol):
    def __call__(self, data: dict) -> Path: ...


class TemplateDirFixture(Protocol):
    def __call__(self, name: str, subdir: str | None = None) -> Path: ...


class ProviderSetupFixture(Protocol):
    def __call__(
        self,
        alias: str,
        *,
        target_dir: str | None = None,
        templates_dir: str = 'templates',
        library_name: str | None = None,
        create_templates: bool = True,
    ) -> tuple[Path, Path]: ...


@pytest.fixture
def yaml_config_file(tmp_path: Path):
    def _create(data: dict) -> Path:
        config_path = tmp_path / 'repolish.yaml'
        with open_utf8(config_path, 'w') as f:
            yaml.dump(data, f)
        return config_path

    return _create


@pytest.fixture
def template_dir(tmp_path: Path):
    def _create(name: str, subdir: str | None = None) -> Path:
        base_path = tmp_path / subdir if subdir else tmp_path
        dir_path = base_path / name
        dir_path.mkdir(parents=True, exist_ok=True)

        (dir_path / 'repolish.py').write_text(
            dedent("""
                def create_context():
                    return {'test': 'value'}
            """),
        )
        (dir_path / 'repolish').mkdir(exist_ok=True)

        return dir_path

    return _create


@pytest.fixture
def provider_setup(tmp_path: Path):
    def _create(
        alias: str,
        *,
        target_dir: str | None = None,
        templates_dir: str = 'templates',
        library_name: str | None = None,
        create_templates: bool = True,
    ) -> tuple[Path, Path]:
        config_dir = tmp_path / 'project'
        config_dir.mkdir(exist_ok=True)

        if target_dir is None:
            target_dir = f'.repolish/{alias}'

        target_path = config_dir / target_dir
        target_path.mkdir(parents=True, exist_ok=True)

        info_file = config_dir / '.repolish' / '_' / f'provider-info.{alias}.json'
        info_file.parent.mkdir(parents=True, exist_ok=True)

        info_data = {
            'target_dir': target_dir,
            'source_dir': f'/fake/source/{alias}',
            'templates_dir': templates_dir,
            'library_name': library_name,
        }

        info_file.write_text(json.dumps(info_data))

        if create_templates:
            templates_path = target_path / templates_dir
            templates_path.mkdir(parents=True, exist_ok=True)
            (templates_path / 'repolish.py').write_text(
                'def create_context():\n    return {}\n',
            )
            (templates_path / 'repolish').mkdir(exist_ok=True)

        return config_dir, target_path

    return _create
