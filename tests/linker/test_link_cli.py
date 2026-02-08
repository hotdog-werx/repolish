"""Tests for repolish.link_cli module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_mock

from repolish.config import ProviderConfig, ProviderSymlink, RepolishConfig
from repolish.link_cli import (
    _get_provider_names,
    _process_single_provider,
    _save_provider_info,
    create_provider_symlinks,
    main,
    run,
    run_provider_link,
)


@pytest.mark.parametrize(
    ('exception', 'should_raise'),
    [
        (None, False),  # Success case
        (subprocess.CalledProcessError(1, 'mylib-link'), True),  # Command fails
    ],
)
def test_run_provider_link_error_handling(
    exception: subprocess.CalledProcessError | None,
    *,
    should_raise: bool,
    mocker: pytest_mock.MockerFixture,
):
    """Test run_provider_link handles success and failure cases."""
    cli_info = {
        'library_name': 'mylib',
        'source_dir': '/path/to/mylib/resources',
        'target_dir': '.repolish/mylib',
        'templates_dir': 'templates',
    }

    mock_run = mocker.patch('subprocess.run')

    if exception is None:
        # Success case
        mock_info = MagicMock()
        mock_info.stdout = json.dumps(cli_info)
        mock_link = MagicMock()
        mock_run.side_effect = [mock_info, mock_link]

        result = run_provider_link('mylib', 'mylib-link')

        assert result == cli_info
        assert mock_run.call_count == 2

        # Verify --info call
        first_call = mock_run.call_args_list[0]
        assert first_call[0][0] == ['mylib-link', '--info']
        assert first_call[1]['capture_output'] is True
        assert first_call[1]['text'] is True
        assert first_call[1]['check'] is True

        # Verify link call
        second_call = mock_run.call_args_list[1]
        assert second_call[0][0] == ['mylib-link']
        assert second_call[1]['check'] is True
    else:
        # Error case
        mock_run.side_effect = exception

        if should_raise:
            with pytest.raises(type(exception)):
                run_provider_link('mylib', 'mylib-link')
        else:
            result = run_provider_link('mylib', 'mylib-link')
            assert result == cli_info


def test_create_provider_symlinks_no_symlinks():
    """Test create_provider_symlinks handles empty symlinks list."""
    cli_info = {'library_name': 'mylib', 'target_dir': '.repolish/mylib'}

    # Should not raise, should just return
    create_provider_symlinks('mylib', cli_info, [])


def test_create_provider_symlinks_creates_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_provider_symlinks creates symlinks from config."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_dir = tmp_path / '.repolish' / 'mylib'
    provider_dir.mkdir(parents=True)
    config_dir = provider_dir / 'configs'
    config_dir.mkdir()
    (config_dir / '.editorconfig').write_text('root = true')
    (config_dir / '.prettierrc').write_text('{}')

    cli_info = {
        'library_name': 'mylib',
        'target_dir': str(provider_dir),
    }

    symlinks = [
        {'source': 'configs/.editorconfig', 'target': '.editorconfig'},
        {'source': 'configs/.prettierrc', 'target': '.prettierrc'},
    ]

    create_provider_symlinks('mylib', cli_info, symlinks)

    # Verify symlinks/copies were created
    assert (tmp_path / '.editorconfig').exists()
    assert (tmp_path / '.prettierrc').exists()
    assert (tmp_path / '.editorconfig').read_text() == 'root = true'
    assert (tmp_path / '.prettierrc').read_text() == '{}'


def test_get_provider_names_with_order():
    """Test _get_provider_names returns providers_order when set."""
    config = RepolishConfig(
        directories=['./templates'],
        providers_order=['lib1', 'lib2', 'lib3'],
        providers={
            'lib1': ProviderConfig(cli='lib1-link'),
            'lib2': ProviderConfig(cli='lib2-link'),
            'lib3': ProviderConfig(cli='lib3-link'),
        },
    )

    result = _get_provider_names(config)

    assert result == ['lib1', 'lib2', 'lib3']


def test_get_provider_names_without_order():
    """Test _get_provider_names returns all providers when no order set."""
    config = RepolishConfig(
        directories=['./templates'],
        providers={
            'lib1': ProviderConfig(cli='lib1-link'),
            'lib2': ProviderConfig(cli='lib2-link'),
        },
    )

    result = _get_provider_names(config)

    # Order is arbitrary but should include all providers
    assert set(result) == {'lib1', 'lib2'}


@pytest.mark.parametrize(
    ('exception', 'expected_result'),
    [
        (None, 0),  # Success case
        (subprocess.CalledProcessError(1, 'cmd'), 1),  # Link command fails
        (FileNotFoundError('not found'), 1),  # CLI not found
    ],
)
def test_process_single_provider_error_handling(
    exception: subprocess.CalledProcessError | FileNotFoundError | None,
    expected_result: int,
    mocker: pytest_mock.MockerFixture,
):
    """Test _process_single_provider handles various error conditions."""
    provider_config = ProviderConfig(cli='mylib-link')

    if exception is None:
        # Success case
        cli_info = {'library_name': 'mylib', 'target_dir': '.repolish/mylib'}
        _ = mocker.patch(
            'repolish.link_cli.run_provider_link',
            return_value=cli_info,
        )
        result = _process_single_provider('mylib', provider_config)
        assert result == expected_result
    else:
        # Error cases
        _ = mocker.patch(
            'repolish.link_cli.run_provider_link',
            side_effect=exception,
        )
        result = _process_single_provider('mylib', provider_config)
        assert result == expected_result


def test_process_single_provider_with_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test _process_single_provider creates additional symlinks."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_dir = tmp_path / '.repolish' / 'mylib'
    provider_dir.mkdir(parents=True)
    (provider_dir / 'config.txt').write_text('content')

    provider_config = ProviderConfig(
        cli='mylib-link',
        symlinks=[
            ProviderSymlink(source='config.txt', target='config.txt'),
        ],
    )

    cli_info = {
        'library_name': 'mylib',
        'target_dir': str(provider_dir),
    }

    _ = mocker.patch(
        'repolish.link_cli.run_provider_link',
        return_value=cli_info,
    )
    result = _process_single_provider('mylib', provider_config)

    assert result == 0
    assert (tmp_path / 'config.txt').exists()


def test_run_no_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test run handles configs with no providers."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    result = run(['--config', str(config_file)])

    assert result == 0


def test_run_with_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run processes providers successfully."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

providers:
  mylib:
    link: mylib-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    cli_info = {
        'library_name': 'mylib',
        'target_dir': '.repolish/mylib',
    }

    mocker.patch(
        'repolish.link_cli.run_provider_link',
        return_value=cli_info,
    )
    result = run(['--config', str(config_file)])

    assert result == 0


def test_run_provider_not_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run handles provider in order but not in providers config."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

providers_order: [lib1, lib2, nonexistent]

providers:
  lib1:
    link: lib1-link
  lib2:
    link: lib2-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    cli_info = {
        'library_name': 'lib',
        'target_dir': '.repolish/lib',
    }

    mocker.patch(
        'repolish.link_cli.run_provider_link',
        return_value=cli_info,
    )
    result = run(['--config', str(config_file)])

    # Should succeed despite missing provider in order
    assert result == 0


def test_run_provider_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run returns error when provider processing fails."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

providers:
  mylib:
    link: mylib-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    mocker.patch(
        'repolish.link_cli.run_provider_link',
        side_effect=subprocess.CalledProcessError(1, 'cmd'),
    )
    result = run(['--config', str(config_file)])

    assert result == 1


@pytest.mark.parametrize(
    ('exception', 'expected_result', 'raises_system_exit'),
    [
        (None, 0, False),  # Success case
        (FileNotFoundError('not found'), 1, False),  # File not found
        (RuntimeError('unexpected'), 1, False),  # Unexpected error
        (SystemExit(42), None, True),  # SystemExit should be re-raised
    ],
)
def test_main_error_handling(
    exception: FileNotFoundError | RuntimeError | SystemExit | None,
    expected_result: int | None,
    *,
    raises_system_exit: bool,
    mocker: pytest_mock.MockerFixture,
):
    """Test main handles various error conditions."""
    if raises_system_exit:
        mocker.patch('repolish.link_cli.run', side_effect=exception)
        with pytest.raises(SystemExit) as exc_info:
            main()
        # In this branch, exception is guaranteed to be SystemExit from parametrize
        assert exc_info.value.code == exception.code  # type: ignore[attr-defined]
    elif exception is None:
        # Success case - patch to return 0
        mocker.patch('repolish.link_cli.run', return_value=0)
        result = main()
        assert result == expected_result
    else:
        # Error cases
        mocker.patch(
            'repolish.link_cli.run',
            side_effect=exception,
        )
        result = main()
        assert result == expected_result


def test_run_with_custom_verbosity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test run respects verbosity flags."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    result = run(['--config', str(config_file), '-v'])

    assert result == 0


def test_save_provider_info(tmp_path: Path):
    """Test that _save_provider_info saves provider info correctly."""
    cli_info = {
        'library_name': 'mylib',
        'source_dir': '/path/to/mylib/resources',
        'target_dir': '.repolish/mylib',
        'templates_dir': 'templates',
    }

    _save_provider_info('mylib', cli_info)

    info_file = Path('.repolish/mylib/.provider-info.json')
    assert info_file.exists()

    saved_info = json.loads(info_file.read_text())
    assert saved_info == cli_info


def test_save_provider_info_with_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that _save_provider_info saves alias when name differs from directory."""
    monkeypatch.chdir(tmp_path)

    # Provider is called "base" in config, but CLI creates "codeguide" directory
    cli_info = {
        'library_name': 'codeguide',
        'source_dir': '/path/to/codeguide/resources',
        'target_dir': '.repolish/codeguide',
        'templates_dir': 'templates',
    }

    _save_provider_info('base', cli_info)

    # Provider info should be saved
    info_file = tmp_path / '.repolish' / 'codeguide' / '.provider-info.json'
    assert info_file.exists()

    saved_info = json.loads(info_file.read_text())
    assert saved_info == cli_info

    # Alias mapping should also be saved
    alias_file = tmp_path / '.repolish' / '.provider-aliases.json'
    assert alias_file.exists()

    aliases = json.loads(alias_file.read_text())
    assert aliases == {'base': '.repolish/codeguide'}


def test_save_provider_info_no_alias_when_names_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that _save_provider_info doesn't create alias when names match."""
    monkeypatch.chdir(tmp_path)

    cli_info = {
        'library_name': 'mylib',
        'source_dir': '/path/to/mylib/resources',
        'target_dir': '.repolish/mylib',
        'templates_dir': 'templates',
    }

    _save_provider_info('mylib', cli_info)

    # Provider info should be saved
    info_file = tmp_path / '.repolish' / 'mylib' / '.provider-info.json'
    assert info_file.exists()

    # No alias file should be created when names match
    alias_file = tmp_path / '.repolish' / '.provider-aliases.json'
    assert not alias_file.exists()


def test_run_provider_link_saves_info(
    mocker: pytest_mock.MockerFixture,
    tmp_path: Path,
):
    """Test that run_provider_link saves provider info after linking."""
    cli_info = {
        'library_name': 'mylib',
        'target_dir': '.repolish/mylib',
        'templates_dir': 'templates',
    }

    mock_run = mocker.patch('subprocess.run')
    mock_info = MagicMock()
    mock_info.stdout = json.dumps(cli_info)
    mock_link = MagicMock()
    mock_run.side_effect = [mock_info, mock_link]

    mock_save = mocker.patch('repolish.link_cli._save_provider_info')

    result = run_provider_link('mylib', 'mylib-link')

    assert result == cli_info
    mock_save.assert_called_once_with('mylib', cli_info)
