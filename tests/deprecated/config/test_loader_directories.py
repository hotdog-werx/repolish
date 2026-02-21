import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from repolish.config import load_config
from repolish.exceptions import DirectoryValidationError
from repolish.utils import open_utf8

if TYPE_CHECKING:
    # Types used by fixtures (provide static-analysis visibility)
    from tests.deprecated.conftest import (
        TemplateDirFixture,
        YamlConfigFileFixture,
    )


def test_load_config_missing_directory(
    yaml_config_file: 'YamlConfigFileFixture',
    tmp_path: Path,
):
    """Test that missing directories are caught during validation."""
    config_data = {
        'directories': ['nonexistent/path'],
    }
    config_path = yaml_config_file(config_data)

    with pytest.raises(DirectoryValidationError, match='Missing directories'):
        load_config(config_path)


def test_load_config_invalid_directory_not_a_directory(
    yaml_config_file: 'YamlConfigFileFixture',
    tmp_path: Path,
):
    """Test that files are rejected when directories are expected."""
    # Create a file instead of a directory
    file_path = tmp_path / 'not_a_dir'
    file_path.write_text('content')

    config_data = {
        'directories': [str(file_path)],
    }
    config_path = yaml_config_file(config_data)

    with pytest.raises(
        DirectoryValidationError,
        match=r'Invalid directories.*not a directory',
    ):
        load_config(config_path)


def test_load_config_missing_repolish_structure(
    yaml_config_file: 'YamlConfigFileFixture',
    tmp_path: Path,
):
    """Test that directories without repolish.py/repolish/ are rejected."""
    # Create directory without required structure
    dir_path = tmp_path / 'incomplete'
    dir_path.mkdir()

    config_data = {
        'directories': [str(dir_path)],
    }
    config_path = yaml_config_file(config_data)

    with pytest.raises(
        DirectoryValidationError,
        match=r'missing repolish.py or repolish/ folder',
    ):
        load_config(config_path)


def test_load_config_with_directories_deprecated_warning(
    yaml_config_file: 'YamlConfigFileFixture',
    template_dir: 'TemplateDirFixture',
):
    """Test that using directories field emits deprecation warning."""
    dir1 = template_dir('test1')

    config_data = {
        'directories': [str(dir1)],
    }
    config_path = yaml_config_file(config_data)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        config = load_config(config_path)

        # Check our specific deprecation warning was raised
        deprecation_warnings = [
            warning
            for warning in w
            if issubclass(warning.category, DeprecationWarning)
            and 'directories' in str(warning.message).lower()
            and 'v1.0' in str(warning.message)
        ]
        assert len(deprecation_warnings) >= 1

    # But it should still work
    assert len(config.directories) == 1
    assert config.directories[0] == dir1.resolve()


def test_load_config_with_absolute_directories(
    yaml_config_file: 'YamlConfigFileFixture',
    template_dir: 'TemplateDirFixture',
):
    """Test loading with absolute directory paths."""
    dir1 = template_dir('test1')
    dir2 = template_dir('test2')

    config_data = {
        'directories': [str(dir1), str(dir2)],
        'context': {'key': 'value'},
    }
    config_path = yaml_config_file(config_data)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        config = load_config(config_path)

    assert len(config.directories) == 2
    assert config.directories[0] == dir1.resolve()
    assert config.directories[1] == dir2.resolve()
    assert config.context == {'key': 'value'}


def test_load_config_with_relative_directories(
    tmp_path: Path,
    template_dir: 'TemplateDirFixture',
):
    """Test that relative directory paths are resolved correctly."""
    # Create config in a subdirectory
    config_dir = tmp_path / 'project'
    config_dir.mkdir()

    # Create template dirs relative to config
    template_dir('templates/base', subdir='project')

    config_data = {
        'directories': ['templates/base'],
    }
    config_path = config_dir / 'repolish.yaml'
    with open_utf8(config_path, 'w') as f:
        yaml.dump(config_data, f)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        config = load_config(config_path)

    assert len(config.directories) == 1
    expected_path = (config_dir / 'templates/base').resolve()
    assert config.directories[0] == expected_path
