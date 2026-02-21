import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from repolish.config import load_config
from repolish.exceptions import (
    ConfigValidationError,
    DirectoryValidationError,
    ProviderConfigError,
    ProviderOrderError,
)
from repolish.utils import open_utf8
from tests.config.conftest import (
    ProviderSetupFixture,
    TemplateDirFixture,
    YamlConfigFileFixture,
)


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
            error_type=ConfigValidationError,
            error_match='must specify either "directories" or "providers"',
        ),
        InvalidConfigCase(
            name='missing_required_fields',
            config_data={'context': {'key': 'value'}},
            error_type=ConfigValidationError,
            error_match='must specify either "directories" or "providers"',
        ),
        InvalidConfigCase(
            name='invalid_provider_config_no_cli_or_directory',
            config_data={
                'providers': {
                    'test': {
                        'templates_dir': 'templates',
                    },
                },
            },
            error_type=ProviderConfigError,
            error_match='Either cli or directory must be provided',
        ),
        InvalidConfigCase(
            name='invalid_provider_config_both_cli_and_directory',
            config_data={
                'providers': {
                    'test': {
                        'cli': 'test-link',
                        'directory': './templates',
                    },
                },
            },
            error_type=ProviderConfigError,
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
            error_type=ProviderOrderError,
            error_match='providers_order references undefined providers: undefined',
        ),
        InvalidConfigCase(
            name='template_overrides_references_undefined_provider',
            config_data={
                'providers_order': ['base'],
                'providers': {
                    'base': {'directory': './templates'},
                },
                'template_overrides': {'README.md': 'undefined'},
            },
            error_type=ConfigValidationError,
            error_match='template_overrides references undefined providers:.*undefined',
        ),
        InvalidConfigCase(
            name='unlinked_provider_with_validation',
            config_data={
                'providers': {
                    'unlinked': {
                        'cli': 'unlinked-link',
                    },
                },
            },
            error_type=DirectoryValidationError,
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


# deprecated test moved to tests/deprecated/config/test_loader_directories.py
# (covers missing-directory validation for the deprecated `directories` config key)


# deprecated test moved to tests/deprecated/config/test_loader_directories.py
# (covers invalid-directory handling for the deprecated `directories` config key)


# deprecated test moved to tests/deprecated/config/test_loader_directories.py
# (covers missing repolish structure for the deprecated `directories` config key)


def test_load_config_missing_symlink_source(
    provider_setup: ProviderSetupFixture,
):
    """Test that missing symlink sources are caught during validation."""
    config_dir, _ = provider_setup('test', create_templates=True)

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
    with open_utf8(config_path, 'w') as f:
        yaml.dump(config_data, f)

    with pytest.raises(
        DirectoryValidationError,
        match='symlink sources not found',
    ):
        load_config(config_path)


# deprecated test moved to tests/deprecated/config/test_loader_directories.py
# (ensures using the deprecated `directories` field emits the expected warning)


# deprecated test moved to tests/deprecated/config/test_loader_directories.py
# (absolute `directories` paths are still resolved; tested under deprecated suite)


# deprecated test moved to tests/deprecated/config/test_loader_directories.py
# (relative `directories` paths resolution moved into deprecated tests)


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
    with open_utf8(config_path, 'w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Should auto-build directories from provider
    assert len(config.directories) == 1
    assert config.directories[0] == templates_path.resolve()

    # Provider should be resolved
    assert 'base' in config.providers
    assert config.providers['base'].target_dir == provider_dir.resolve()
    assert config.providers['base'].templates_dir == 'templates'


def test_load_config_template_overrides_roundtrip(
    yaml_config_file: YamlConfigFileFixture,
):
    """Ensure template_overrides entries survive validation/resolution."""
    config_data = {
        'providers_order': ['test'],
        'providers': {
            'test': {'directory': './templates'},
        },
        'template_overrides': {'README.md': 'test'},
    }
    config_path = yaml_config_file(config_data)

    # create the resolved provider directory structure so validation passes
    cfg_dir = config_path.parent
    provider_dir = cfg_dir / 'templates'
    # config resolution will append another ``templates`` segment, so create
    # ``templates/templates`` and give it a minimal repolish layout
    real_templates = provider_dir / 'templates'
    rep = real_templates / 'repolish'
    rep.mkdir(parents=True)
    # also touch a dummy repolish.py so validation is happy
    (real_templates / 'repolish.py').write_text('')

    config = load_config(config_path)
    assert config.template_overrides == {'README.md': 'test'}


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
    with open_utf8(config_path, 'w') as f:
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
    with open_utf8(config_path, 'w') as f:
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
    with open_utf8(config_path, 'w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Symlinks should be preserved and converted to Path objects
    assert 'test' in config.providers
    assert len(config.providers['test'].symlinks) == 1
    symlink = config.providers['test'].symlinks[0]
    assert symlink.source == Path('configs/editorconfig')
    assert symlink.target == Path('.editorconfig')


def test_load_config_with_provider_default_symlinks(
    provider_setup: ProviderSetupFixture,
):
    """Test that provider default symlinks are used when user doesn't specify any."""
    config_dir, target_dir = provider_setup('test', create_templates=True)

    # Create the symlink source files
    configs_dir = target_dir / 'configs'
    configs_dir.mkdir()
    (configs_dir / '.editorconfig').write_text('# editorconfig')
    (configs_dir / '.gitignore').write_text('# gitignore')

    # Write provider info with default symlinks
    info_file = config_dir / '.repolish' / '_' / 'provider-info.test.json'
    info_file.write_text(
        json.dumps(
            {
                'target_dir': str(target_dir),
                'source_dir': '/fake/source',
                'templates_dir': 'templates',
                'library_name': 'test',
                'symlinks': [
                    {
                        'source': 'configs/.editorconfig',
                        'target': '.editorconfig',
                    },
                    {'source': 'configs/.gitignore', 'target': '.gitignore'},
                ],
            },
        ),
    )

    config_data = {
        'providers_order': ['test'],
        'providers': {
            'test': {
                'cli': 'test-link',
                # Note: no symlinks specified - should use provider defaults
            },
        },
    }
    config_path = config_dir / 'repolish.yaml'
    with open_utf8(config_path, 'w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Should use provider's default symlinks
    assert 'test' in config.providers
    assert len(config.providers['test'].symlinks) == 2
    assert config.providers['test'].symlinks[0].source == Path(
        'configs/.editorconfig',
    )
    assert config.providers['test'].symlinks[0].target == Path('.editorconfig')
    assert config.providers['test'].symlinks[1].source == Path(
        'configs/.gitignore',
    )
    assert config.providers['test'].symlinks[1].target == Path('.gitignore')


def test_load_config_override_provider_symlinks_with_empty_list(
    provider_setup: ProviderSetupFixture,
):
    """Test that user can override provider symlinks with empty list (no symlinks)."""
    config_dir, target_dir = provider_setup('test', create_templates=True)

    # Create the symlink source files (even though they won't be used)
    configs_dir = target_dir / 'configs'
    configs_dir.mkdir()
    (configs_dir / '.editorconfig').write_text('# editorconfig')

    # Write provider info with default symlinks
    info_file = config_dir / '.repolish' / '_' / 'provider-info.test.json'
    info_file.write_text(
        json.dumps(
            {
                'target_dir': str(target_dir),
                'source_dir': '/fake/source',
                'templates_dir': 'templates',
                'library_name': 'test',
                'symlinks': [
                    {
                        'source': 'configs/.editorconfig',
                        'target': '.editorconfig',
                    },
                ],
            },
        ),
    )

    config_data = {
        'providers_order': ['test'],
        'providers': {
            'test': {
                'cli': 'test-link',
                'symlinks': [],  # Explicitly override with no symlinks
            },
        },
    }
    config_path = config_dir / 'repolish.yaml'
    with open_utf8(config_path, 'w') as f:
        yaml.dump(config_data, f)

    config = load_config(config_path)

    # Should use user's override (empty list)
    assert 'test' in config.providers
    assert len(config.providers['test'].symlinks) == 0


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


def test_load_config_providers_order_optional(
    provider_setup: ProviderSetupFixture,
):
    """Test that providers_order is optional and defaults to providers dict key order."""
    config_dir, target1 = provider_setup('base', create_templates=True)
    _, target2 = provider_setup('python', create_templates=True)
    _, target3 = provider_setup('extras', create_templates=True)

    # Config WITHOUT providers_order - should use dict key order from YAML
    config_data = {
        'providers': {
            'base': {'directory': str(target1)},
            'python': {'directory': str(target2)},
            'extras': {'directory': str(target3)},
        },
    }
    config_path = config_dir / 'repolish.yaml'
    with open_utf8(config_path, 'w') as f:
        yaml.dump(config_data, f, sort_keys=False)  # Preserve order

    config = load_config(config_path)

    # Should process providers in the order they appear in the YAML (dict key order)
    assert len(config.directories) == 3
    assert config.directories[0].name == 'templates'
    assert config.directories[0].parent.name == 'base'
    assert config.directories[1].parent.name == 'python'
    assert config.directories[2].parent.name == 'extras'
