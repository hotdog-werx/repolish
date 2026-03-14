import json
from pathlib import Path
from textwrap import dedent
from typing import Protocol

import pytest
import yaml

from repolish.utils import open_utf8


class YamlConfigFileFixture(Protocol):
    """Type for yaml_config_file fixture callable."""

    def __call__(self, data: dict) -> Path:
        """Create YAML config file from dict data.

        Args:
            data: Dictionary to write as YAML

        Returns:
            Path to created config file
        """
        ...


class TemplateDirFixture(Protocol):
    """Type for template_dir fixture callable."""

    def __call__(self, name: str, subdir: str | None = None) -> Path:
        """Create a valid repolish template directory.

        Args:
            name: Directory name
            subdir: Optional subdirectory to create template in

        Returns:
            Path to created template directory
        """
        ...


class ProviderSetupFixture(Protocol):
    """Type for provider_setup fixture callable."""

    def __call__(
        self,
        alias: str,
        *,
        target_dir: str | None = None,
        create_templates: bool = True,
    ) -> tuple[Path, Path]:
        """Create provider setup with info file.

        Args:
            alias: Provider alias name
            target_dir: Relative path to target directory (created if None)
            create_templates: Whether to create actual template structure

        Returns:
            Tuple of (config_dir, provider_target_dir)
        """
        ...


@pytest.fixture
def yaml_config_file(tmp_path: Path):
    """Fixture to create YAML config files from dict data."""

    def _create(data: dict) -> Path:
        config_path = tmp_path / 'repolish.yaml'
        with open_utf8(config_path, 'w') as f:
            yaml.dump(data, f)
        return config_path

    return _create


@pytest.fixture
def template_dir(tmp_path: Path):
    """Fixture to create a valid repolish template directory."""

    def _create(name: str, subdir: str | None = None) -> Path:
        base_path = tmp_path / subdir if subdir else tmp_path
        dir_path = base_path / name
        dir_path.mkdir(parents=True, exist_ok=True)

        # Create required repolish structure
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
    """Fixture to set up provider directories and info files."""

    def _create(
        alias: str,
        *,
        target_dir: str | None = None,
        create_templates: bool = True,
    ) -> tuple[Path, Path]:
        """Create provider setup with info file.

        Args:
            alias: Provider alias name
            target_dir: Relative path to target directory (created if None)
            create_templates: Whether to create actual template structure

        Returns:
            Tuple of (config_dir, provider_target_dir)
        """
        config_dir = tmp_path / 'project'
        config_dir.mkdir(exist_ok=True)

        # Determine target directory
        if target_dir is None:
            target_dir = f'.repolish/{alias}'

        target_path = config_dir / target_dir
        target_path.mkdir(parents=True, exist_ok=True)

        # Create provider info file
        info_file = config_dir / '.repolish' / '_' / f'provider-info.{alias}.json'
        info_file.parent.mkdir(parents=True, exist_ok=True)

        info_data = {
            'resources_dir': target_dir,
            'site_package_dir': f'/fake/source/{alias}',
        }

        info_file.write_text(json.dumps(info_data))

        # Optionally create template structure in the provider root
        if create_templates:
            (target_path / 'repolish.py').write_text(
                'def create_context():\n    return {}\n',
            )
            (target_path / 'repolish').mkdir(exist_ok=True)

        return config_dir, target_path

    return _create
