import warnings
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from repolish.config import load_config

from .conftest import ProviderSetupFixture, TemplateDirFixture, YamlConfigFileFixture


@dataclass
class InvalidConfigCase:
    """Test case for configurations that should fail validation."""

    name: str
    config_data: dict
    error_type: type[Exception]
    error_match: str


@pytest.mark.parametrize(
    'case',
    [
        InvalidConfigCase(
            name='empty_config',
            config_data={},
            error_type=ValueError,
            error_match='must specify either "directories" or "providers_order"',
        ),
        InvalidConfigCase(
            name='missing_required_fields',
            config_data={'context': {'key': 'value'}},
            error_type=ValueError,
            error_match='must specify either "directories" or "providers_order"',
        ),
        InvalidConfigCase(
            name='invalid_provider_config_no_cli_or_directory',
            config_data={
                'providers_order': ['test'],
                'providers': {
                    'test': {
                        'templates_dir': 'templates',
                    },
                },
            },
            error_type=ValueError,
            error_match='Either cli or directory must be provided',
        ),
        InvalidConfigCase(
            name='invalid_provider_config_both_cli_and_directory',
            config_data={
                'providers_order': ['test'],
                'providers': {
                    'test': {
                        'cli': 'test-link',
                        'directory': './templates',
                    },
                },
            },
            error_type=ValueError,
            error_match='Cannot specify both cli and directory',
        ),
        InvalidConfigCase(
            name='providers_order_references_undefined_provider',
            config_data={
                'providers_order': ['base', 'undefined'],
                'providers': {
                    'base': {
                        'directory': './templates',
                    },
                },
            },
            error_type=ValueError,
            error_match='providers_order references undefined providers: undefined',
        ),
        InvalidConfigCase(
            name='unlinked_provider_with_validation',
            config_data={
                'providers_order': ['unlinked'],
                'providers': {
                    'unlinked': {
                        'cli': 'unlinked-link',
                    },
                },
            },
            error_type=ValueError,
            error_match='No directories resolved - providers may not be linked yet',
        ),
    ],
    ids=lambda case: case.name,
)
def test_load_config_validation_failures(
    yaml_config_file: YamlConfigFileFixture,
    case: InvalidConfigCase,
):
    """Test that invalid configurations raise appropriate errors."""
    config_path = yaml_config_file(case.config_data)

    with pytest.raises(case.error_type, match=case.error_match):
        load_config(config_path)


def test_load_config_missing_directory(
    yaml_config_file: YamlConfigFileFixture,
    tmp_path: Path,
):
    """Test that missing directories are caught during validation."""
    config_data = {
        'directories': ['nonexistent/path'],
    }
    config_path = yaml_config_file(config_data)

    with pytest.raises(ValueError, match='Missing directories'):
        load_config(config_path)


def test_load_config_invalid_directory_not_a_directory(
    yaml_config_file: YamlConfigFileFixture,
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

    with pytest.raises(ValueError, match='Invalid directories.*not a directory'):
        load_config(config_path)


def test_load_config_missing_repolish_structure(
    yaml_config_file: YamlConfigFileFixture,
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
        ValueError,
        match='missing repolish.py or repolish/ folder',
    ):
        load_config(config_path)


def test_load_config_missing_symlink_source(
    provider_setup: ProviderSetupFixture,
):
    """Test that missing symlink sources are caught during validation."""
    config_dir, target_dir = provider_setup('test', create_templates=True)

    # Provider is linked (has info file), but symlink source doesn't exist
    config_data = {
        'providers_order': ['test'],
        'providers': {
            'test': {
                'cli': 'test-link',
                'symlinks': [
                    {
                        'source': 'configs/missing.txt',
                        'target': '.editorconfig',
                    },
                ],
            },
        },
    }

    config_path = config_dir / 'repolish.yaml'
    with config_path.open('w') as f:
        yaml.dump(config_data, f)

    with pytest.raises(ValueError, match='symlink sources not found'):
        load_config(config_path)


def test_load_config_with_directories_deprecated_warning(
    yaml_config_file: YamlConfigFileFixture,
    template_dir: TemplateDirFixture,
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
            warning for warning in w
            if issubclass(warning.category, DeprecationWarning)
            and 'directories' in str(warning.message).lower()
            and 'v1.0' in str(warning.message)
        ]
        assert len(deprecation_warnings) >= 1

    # But it should still work
    assert len(config.directories) == 1
    assert config.directories[0] == dir1.resolve()


def test_load_config_with_absolute_directories(
    yaml_config_file: YamlConfigFileFixture,
    template_dir: TemplateDirFixture,
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
    template_dir: TemplateDirFixture,
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
    with config_path.open('w') as f:
        yaml.dump(config_data, f)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        config = load_config(config_path)

    assert len(config.directories) == 1
    expected_path = (config_dir / 'templates/base').resolve()
    assert config.directories[0] == expected_path


def test_load_config_with_provider_directory(
    tmp_path: Path,
    template_dir: TemplateDirFixture,
):
    """Test loading with provider using directory configuration."""
    config_dir = tmp_path / 'project'
    config_dir.mkdir()

    # Create provider directory
    provider_dir = config_dir / 'my-provider'
    templates_path = provider_dir / 'templates'
    templates_path.mkdir(parents=True)
    (templates_path / 'repolish.py').write_text(
        'def create_context():\n    return {}\n',
    )
    (templates_path / 'repolish').mkdir()

    config_data = {
        'providers_order': ['base'],
        'providers': {
            'base': {
                'directory': 'my-provider',
            },
        },
    }
    config_path = config_dir / 'repolish.yaml'
    with config_path.open('w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Should auto-build directories from provider
    assert len(config.directories) == 1
    assert config.directories[0] == templates_path.resolve()

    # Provider should be resolved
    assert 'base' in config.providers
    assert config.providers['base'].target_dir == provider_dir.resolve()
    assert config.providers['base'].templates_dir == 'templates'


def test_load_config_with_linked_provider(provider_setup: ProviderSetupFixture):
    """Test loading with provider that has been linked (has info file)."""
    config_dir, target_dir = provider_setup(
        'mylib',
        library_name='my-library',
        create_templates=True,
    )

    config_data = {
        'providers_order': ['mylib'],
        'providers': {
            'mylib': {
                'cli': 'mylib-link',
            },
        },
    }
    config_path = config_dir / 'repolish.yaml'
    with config_path.open('w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Should auto-build directories from linked provider
    assert len(config.directories) == 1
    expected_templates = target_dir / 'templates'
    assert config.directories[0] == expected_templates.resolve()

    # Provider should be resolved with info from JSON
    assert 'mylib' in config.providers
    assert config.providers['mylib'].target_dir == target_dir.resolve()
    assert config.providers['mylib'].library_name == 'my-library'
    assert config.providers['mylib'].templates_dir == 'templates'


def test_load_config_multiple_providers(provider_setup: ProviderSetupFixture):
    """Test loading with multiple providers in order."""
    config_dir, target1 = provider_setup('base', create_templates=True)
    _, target2 = provider_setup('python', create_templates=True)

    config_data = {
        'providers_order': ['base', 'python'],
        'providers': {
            'base': {'cli': 'base-link'},
            'python': {'cli': 'python-link'},
        },
    }
    config_path = config_dir / 'repolish.yaml'
    with config_path.open('w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Directories should be in providers_order
    assert len(config.directories) == 2
    assert config.directories[0] == (target1 / 'templates').resolve()
    assert config.directories[1] == (target2 / 'templates').resolve()
    assert config.providers_order == ['base', 'python']


def test_load_config_with_symlinks(provider_setup: ProviderSetupFixture):
    """Test loading provider with symlinks."""
    config_dir, target_dir = provider_setup('test', create_templates=True)

    # Create the symlink source file
    configs_dir = target_dir / 'configs'
    configs_dir.mkdir()
    (configs_dir / 'editorconfig').write_text('# config')

    config_data = {
        'providers_order': ['test'],
        'providers': {
            'test': {
                'cli': 'test-link',
                'symlinks': [
                    {
                        'source': 'configs/editorconfig',
                        'target': '.editorconfig',
                    },
                ],
            },
        },
    }
    config_path = config_dir / 'repolish.yaml'
    with config_path.open('w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Symlinks should be preserved and converted to Path objects
    assert 'test' in config.providers
    assert len(config.providers['test'].symlinks) == 1
    symlink = config.providers['test'].symlinks[0]
    assert symlink.source == Path('configs/editorconfig')
    assert symlink.target == Path('.editorconfig')


def test_load_config_skip_validation_for_linking(
    yaml_config_file: YamlConfigFileFixture,
):
    """Test that validate=False skips path validation (for linking)."""
    # Provider not linked yet, so no info file exists
    config_data = {
        'providers_order': ['unlinked'],
        'providers': {
            'unlinked': {
                'cli': 'unlinked-link',
            },
        },
    }
    config_path = yaml_config_file(config_data)

    # Should not raise even though provider is not linked
    config = load_config(config_path, validate=False)

    # Provider is not linked and has no directory, so it won't be in providers dict
    assert config.directories == []  # No directories since not linked
    assert 'unlinked' not in config.providers  # Not resolved
    assert config.providers_order == ['unlinked']  # But order preserved


def test_load_config_all_fields(
    yaml_config_file: YamlConfigFileFixture,
    template_dir: TemplateDirFixture,
):
    """Test loading config with all optional fields populated."""
    dir1 = template_dir('test1')

    config_data = {
        'directories': [str(dir1)],
        'context': {'project': 'test'},
        'context_overrides': {'nested.key': 'value'},
        'anchors': {'header': '# Header'},
        'post_process': ['black .', 'ruff check .'],
        'delete_files': ['old.txt', '!keep.txt'],
    }
    config_path = yaml_config_file(config_data)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        config = load_config(config_path)

    assert config.context == {'project': 'test'}
    assert config.context_overrides == {'nested.key': 'value'}
    assert config.anchors == {'header': '# Header'}
    assert config.post_process == ['black .', 'ruff check .']
    assert config.delete_files == ['old.txt', '!keep.txt']
    assert config.config_dir == config_path.parent.resolve()
