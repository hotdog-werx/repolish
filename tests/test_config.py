from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from repolish.config import load_config
from repolish.loader import create_providers


def test_load_config_and_create_context(
    tmp_path: Path,
    temp_repolish_dirs: list[str],
):
    """Test loading config and creating context from template directories."""
    # Create a temporary config YAML file
    config_data = {
        'directories': temp_repolish_dirs,
        'context': {'project_name': 'MyProject'},
        'post_process': ["echo 'Done'"],
    }

    config_file = tmp_path / 'repolish.yaml'
    with config_file.open('w') as f:
        yaml.dump(config_data, f)

    # Load the config
    config = load_config(config_file)

    # Verify config was loaded correctly
    assert config.directories == temp_repolish_dirs
    assert config.context == {'project_name': 'MyProject'}
    assert config.post_process == ["echo 'Done'"]

    # Create providers from the directories
    providers = create_providers(config.directories)
    context = providers.context

    # Verify the merged context
    expected_context = {
        'name': 'Template1',
        'version': '1.0',
        'author': 'Test Author',
        'description': 'A test template',
        'license': 'MIT',
        'year': 2023,
        'framework': 'pytest',
        'language': 'python',
    }
    assert context == expected_context


def test_config_missing_directories(tmp_path: Path):
    """Test config validation raises error for missing directories."""
    nonexistent_dir = str(tmp_path / 'nonexistent')
    config_data = {
        'directories': [nonexistent_dir],
        'context': {},
        'post_process': [],
    }
    config_file = tmp_path / 'repolish.yaml'
    with config_file.open('w') as f:
        yaml.dump(config_data, f)

    with pytest.raises(ValueError, match='Missing directories'):
        load_config(config_file)


def test_config_invalid_directories(tmp_path: Path):
    """Test config validation raises error for paths that are not directories."""
    not_a_dir = tmp_path / 'not_a_dir'
    not_a_dir.write_text("I'm a file, not a dir")
    config_data = {
        'directories': [str(not_a_dir)],
        'context': {},
        'post_process': [],
    }
    config_file = tmp_path / 'repolish.yaml'
    with config_file.open('w') as f:
        yaml.dump(config_data, f)

    with pytest.raises(
        ValueError,
        match='Invalid directories \\(not a directory\\)',
    ):
        load_config(config_file)


def test_config_missing_repolish_py(tmp_path: Path):
    """Test config validation raises error for directories missing repolish.py."""
    missing_repolish_dir = tmp_path / 'missing_repolish'
    missing_repolish_dir.mkdir()
    config_data = {
        'directories': [str(missing_repolish_dir)],
        'context': {},
        'post_process': [],
    }
    config_file = tmp_path / 'repolish.yaml'
    with config_file.open('w') as f:
        yaml.dump(config_data, f)

    with pytest.raises(ValueError, match=r'Directories missing repolish.py'):
        load_config(config_file)


def test_create_context_no_create_function(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    """Test create_context logs warning for templates without create_context function."""
    # Create a directory with repolish.py but no create_context function
    invalid_dir = tmp_path / 'invalid_template'
    invalid_dir.mkdir()
    invalid_repolish_py = invalid_dir / 'repolish.py'
    invalid_repolish_py.write_text(
        dedent("""
        # No create_context function here
        def some_other_func():
            return "not create_context"
    """),
    )

    # Create providers should return empty context when no create_context
    providers = create_providers([str(invalid_dir)])
    assert providers.context == {}


def test_create_context_malformed_py(tmp_path: Path):
    """Test create_context raises SyntaxError for malformed repolish.py."""
    # Create a directory with malformed repolish.py
    malformed_dir = tmp_path / 'malformed_template'
    malformed_dir.mkdir()
    malformed_repolish_py = malformed_dir / 'repolish.py'
    malformed_repolish_py.write_text(
        dedent("""
        def create_context()
            return {"malformed": True  # missing colon
    """),
    )

    # Creating providers should raise SyntaxError when module is malformed
    with pytest.raises(SyntaxError):
        create_providers([str(malformed_dir)])


def test_get_directories_resolves_relative_to_config(tmp_path: Path):
    # Create a config directory and a template dir inside it
    config_dir = tmp_path / 'cfg'
    config_dir.mkdir()
    template_dir = config_dir / 'templates' / 'template1'
    template_dir.mkdir(parents=True)
    # create required repolish.py so load_config validation passes
    (template_dir / 'repolish.py').write_text('# dummy')

    # Write YAML with a POSIX-style relative path
    config_data = {
        'directories': ['templates/template1'],
        'context': {},
        'post_process': [],
    }
    config_file = config_dir / 'repolish.yaml'
    with config_file.open('w') as f:
        yaml.dump(config_data, f)

    cfg = load_config(config_file)
    dirs = cfg.get_directories()
    assert len(dirs) == 1
    assert dirs[0] == (template_dir.resolve())


def test_get_directories_preserves_absolute_posix(tmp_path: Path):
    # Absolute POSIX-style entries should be interpreted as absolute paths
    # on the host platform.
    abs_dir = tmp_path / 'abs_template'
    abs_dir.mkdir()
    (abs_dir / 'repolish.py').write_text('# dummy')

    # Simulate a YAML that used POSIX formatting for the absolute path
    posix_abs = abs_dir.as_posix()
    config_file = tmp_path / 'repolish.yaml'
    with config_file.open('w') as f:
        yaml.dump(
            {'directories': [posix_abs], 'context': {}, 'post_process': []},
            f,
        )

    cfg = load_config(config_file)
    dirs = cfg.get_directories()
    assert len(dirs) == 1
    assert dirs[0] == abs_dir.resolve()
