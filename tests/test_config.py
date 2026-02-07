import json
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
import pytest_mock
import yaml

from repolish.config import RepolishConfig, load_config
from repolish.loader import create_providers


def _create_file(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def _create_dir(path: Path) -> Path:
    path.mkdir()
    return path


@pytest.fixture
def config_file(tmp_path: Path):
    """Fixture to create a config file from data."""

    def _create_config(config_data: dict) -> Path:
        config_file = tmp_path / 'repolish.yaml'
        with config_file.open('w') as f:
            yaml.dump(config_data, f)
        return config_file

    return _create_config


@pytest.fixture
def template_dir(tmp_path: Path):
    """Fixture to create a basic template directory with repolish.py."""

    def _create_template(name: str = 'template') -> Path:
        template_dir = tmp_path / name
        template_dir.mkdir()
        (template_dir / 'repolish.py').write_text('# dummy')
        (template_dir / 'repolish').mkdir()
        return template_dir

    return _create_template


@pytest.fixture
def provider_info(tmp_path: Path):
    """Fixture to create provider info JSON files."""

    def _create_provider(
        name: str,
        templates_dir: str = 'templates',
        **kwargs: Any,
    ) -> Path:
        provider_dir = tmp_path / '.repolish' / name
        provider_dir.mkdir(parents=True)
        info = {
            'library_name': name,
            'target_dir': f'.repolish/{name}',
            'templates_dir': templates_dir,
            **kwargs,
        }
        with (provider_dir / '.provider-info.json').open('w') as f:
            json.dump(info, f)
        # Create templates dir
        (provider_dir / templates_dir).mkdir()
        return provider_dir

    return _create_provider


def test_load_config_and_create_context(
    tmp_path: Path,
    temp_repolish_dirs: list[str],
    config_file: Callable[[dict], Path],
):
    """Test loading config and creating context from template directories."""
    # Create a temporary config YAML file
    config_data = {
        'directories': temp_repolish_dirs,
        'context': {'project_name': 'MyProject'},
        'post_process': ["echo 'Done'"],
    }

    config_path = config_file(config_data)

    # Load the config
    config = load_config(config_path)

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


@pytest.mark.parametrize(
    ('setup_func', 'expected_match'),
    [
        (lambda tmp_path: str(tmp_path / 'nonexistent'), 'Missing directories'),
        (
            lambda tmp_path: str(
                _create_file(tmp_path / 'not_a_dir', "I'm a file, not a dir"),
            ),
            'Invalid directories \\(not a directory\\)',
        ),
        (
            lambda tmp_path: str(_create_dir(tmp_path / 'missing_repolish')),
            r'Directories missing repolish.py',
        ),
    ],
    ids=['missing_directories', 'invalid_directories', 'missing_repolish_py'],
)
def test_config_validation_errors(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
    setup_func: Callable[[Path], str],
    expected_match: str,
):
    """Test config validation raises errors for various invalid directory setups."""
    invalid_path = setup_func(tmp_path)
    config_data = {
        'directories': [invalid_path],
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    with pytest.raises(ValueError, match=expected_match):
        load_config(config_path)


@pytest.mark.parametrize(
    ('repolish_content', 'expected_exception'),
    [
        (
            dedent("""
            # No create_context function here
            def some_other_func():
                return "not create_context"
            """),
            None,  # Should not raise, just return empty context
        ),
        (
            dedent("""
            def create_context()
                return {"malformed": True  # missing colon
            """),
            SyntaxError,
        ),
    ],
    ids=['no_create_function', 'malformed_py'],
)
def test_create_providers_edge_cases(
    tmp_path: Path,
    repolish_content: str,
    expected_exception: type[Exception] | None,
):
    """Test create_providers handles various repolish.py edge cases."""
    template_dir = tmp_path / 'template'
    template_dir.mkdir()
    repolish_py = template_dir / 'repolish.py'
    repolish_py.write_text(repolish_content)

    if expected_exception:
        with pytest.raises(expected_exception):
            create_providers([str(template_dir)])
    else:
        providers = create_providers([str(template_dir)])
        assert providers.context == {}


def test_get_directories_resolves_relative_to_config(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
    template_dir: Callable[[str], Path],
):
    # Create a config directory and a template dir inside it
    config_dir = tmp_path / 'cfg'
    config_dir.mkdir()
    template_path = config_dir / 'templates' / 'template1'
    template_path.mkdir(parents=True)
    # create required repolish.py so load_config validation passes
    (template_path / 'repolish.py').write_text('# dummy')
    (template_path / 'repolish').mkdir(parents=True, exist_ok=True)

    # Write YAML with a POSIX-style relative path
    config_data = {
        'directories': ['templates/template1'],
        'context': {},
        'post_process': [],
    }
    config_path = config_dir / 'repolish.yaml'
    with config_path.open('w') as f:
        yaml.dump(config_data, f)

    cfg = load_config(config_path)
    dirs = cfg.get_directories()
    assert len(dirs) == 1
    assert dirs[0] == (template_path.resolve())


def test_get_directories_preserves_absolute_posix(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
    template_dir: Callable[[str], Path],
):
    # Absolute POSIX-style entries should be interpreted as absolute paths
    # on the host platform.
    abs_dir = template_dir('abs_template')

    # Simulate a YAML that used POSIX formatting for the absolute path
    posix_abs = abs_dir.as_posix()
    config_data = {
        'directories': [posix_abs],
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    cfg = load_config(config_path)
    dirs = cfg.get_directories()
    assert len(dirs) == 1
    assert dirs[0] == abs_dir.resolve()


def test_config_allows_empty_directories_with_providers_order(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
):
    """Test that directories can be empty if providers_order is set."""
    config_data = {
        'providers_order': ['provider1', 'provider2'],
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    # Should not raise - providers_order is set
    config = load_config(config_path)
    assert config.directories == []
    assert config.providers_order == ['provider1', 'provider2']


def test_config_requires_directories_or_providers_order(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
):
    """Test that either directories or providers_order must be specified."""
    config_data = {
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    # Should raise - neither directories nor providers_order is set
    with pytest.raises(
        ValueError,
        match='Either directories or providers_order must be specified',
    ):
        load_config(config_path)


def test_build_directories_from_providers(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
    provider_info: Callable[..., Path],
):
    """Test building directories from providers_order using saved provider info."""
    # Create provider info files
    provider_info('provider1')
    provider_info('provider2', 'custom-templates')

    # Create config with providers_order
    config_data = {
        'providers_order': ['provider1', 'provider2'],
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    config = load_config(config_path)
    directories = config.get_directories()

    assert len(directories) == 2
    assert directories[0] == (tmp_path / '.repolish' / 'provider1' / 'templates').resolve()
    assert directories[1] == (tmp_path / '.repolish' / 'provider2' / 'custom-templates').resolve()


def test_build_directories_warns_on_missing_provider_info(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    config_file: Callable[[dict], Path],
    provider_info: Callable[..., Path],
):
    """Test that missing provider info logs a warning but continues."""
    # Create info for only provider1, not provider2
    provider_info('provider1')

    # Create config with both providers
    config_data = {
        'providers_order': ['provider1', 'provider2'],
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    config = load_config(config_path)
    directories = config.get_directories()

    # Should only have provider1
    assert len(directories) == 1
    assert directories[0] == (tmp_path / '.repolish' / 'provider1' / 'templates').resolve()


def test_build_directories_from_providers_no_config_file(tmp_path: Path):
    """Test that building from providers returns empty list when config_file is None."""
    config_data = {
        'providers_order': ['provider1'],
        'context': {},
        'post_process': [],
    }
    config = RepolishConfig.model_validate(config_data)
    # config_file is None
    assert config.config_file is None

    # Should return empty list
    directories = config.get_directories()
    assert directories == []


def test_load_provider_info_invalid_json(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
    provider_info: Callable[..., Path],
):
    """Test that invalid JSON in provider info is handled gracefully."""
    provider_dir = provider_info('provider1')

    # Overwrite with invalid JSON
    (provider_dir / '.provider-info.json').write_text('{ invalid json }')

    config_data = {
        'providers_order': ['provider1'],
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    config = load_config(config_path)
    directories = config.get_directories()

    # Should return empty list due to invalid JSON
    assert directories == []


def test_load_provider_info_oserror(
    tmp_path: Path,
    config_file: Callable[[dict], Path],
    provider_info: Callable[..., Path],
    mocker: pytest_mock.MockerFixture,
):
    """Test that OSError when reading provider info is handled gracefully."""
    provider_dir = provider_info('provider1')

    # Mock Path.open to raise OSError for the specific file
    info_file = provider_dir / '.provider-info.json'
    original_open = Path.open

    def mock_open(self: Path, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - overriding open in tests
        if self == info_file and 'r' in args:
            mocked_read_error = 'Mocked read error'
            raise OSError(mocked_read_error)
        return original_open(self, *args, **kwargs)

    mocker.patch.object(Path, 'open', mock_open)

    config_data = {
        'providers_order': ['provider1'],
        'context': {},
        'post_process': [],
    }
    config_path = config_file(config_data)

    config = load_config(config_path)
    directories = config.get_directories()

    # Should return empty list due to OSError
    assert directories == []
