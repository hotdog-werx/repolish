from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from repolish.config import load_config
from repolish.loader import create_context


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

    # Create context from the directories
    context = create_context(config.directories)

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

    # Create context should log warning
    context = create_context([str(invalid_dir)])

    # Check that warning was printed to stdout
    captured = capsys.readouterr()
    assert 'create_context_not_found' in captured.out
    assert f'module={invalid_dir}/repolish.py' in captured.out

    # Context should be empty
    assert context == {}


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

    # Create context should raise SyntaxError
    with pytest.raises(SyntaxError):
        create_context([str(malformed_dir)])
