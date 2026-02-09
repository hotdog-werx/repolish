"""Tests for repolish.link_cli module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_mock

from repolish.config import ProviderConfig, ProviderInfo, ProviderSymlink
from repolish.config.models import RepolishConfigFile
from repolish.link_cli import (
    _get_provider_names,
    main,
    run,
)
from repolish.linker import (
    create_provider_symlinks,
    process_provider,
    run_provider_link,
    save_provider_info,
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
    provider_info_data = {
        'library_name': 'mylib',
        'target_dir': '.repolish/mylib',
        'source_dir': '/fake/source/mylib',
        'templates_dir': 'templates',
    }

    mock_run = mocker.patch('subprocess.run')

    if exception is None:
        # Success case
        mock_info = MagicMock()
        mock_info.stdout = json.dumps(provider_info_data)
        mock_link = MagicMock()
        mock_run.side_effect = [mock_info, mock_link]

        result = run_provider_link('mylib', 'mylib-link')

        assert isinstance(result, ProviderInfo)
        assert result.library_name == 'mylib'
        assert result.target_dir == '.repolish/mylib'
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
            assert isinstance(result, ProviderInfo)


def test_create_provider_symlinks_no_symlinks():
    """Test create_provider_symlinks handles empty symlinks list."""
    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir='.repolish/mylib',
        source_dir='/fake/source/mylib',
    )

    # Should not raise, should just return
    create_provider_symlinks('mylib', provider_info, [])


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

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_dir),
        source_dir='/fake/source/mylib',
    )

    symlinks = [
        ProviderSymlink(
            source=Path('configs/.editorconfig'),
            target=Path('.editorconfig'),
        ),
        ProviderSymlink(
            source=Path('configs/.prettierrc'),
            target=Path('.prettierrc'),
        ),
    ]

    create_provider_symlinks('mylib', provider_info, symlinks)

    # Verify symlinks/copies were created
    assert (tmp_path / '.editorconfig').exists()
    assert (tmp_path / '.prettierrc').exists()
    assert (tmp_path / '.editorconfig').read_text() == 'root = true'
    assert (tmp_path / '.prettierrc').read_text() == '{}'


def test_get_provider_names_with_order():
    """Test _get_provider_names returns providers_order when set."""
    config = RepolishConfigFile(
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
    config = RepolishConfigFile(
        providers={
            'lib1': ProviderConfig(cli='lib1-link'),
            'lib2': ProviderConfig(cli='lib2-link'),
            'local': ProviderConfig(directory='./templates'),
        },
    )

    result = _get_provider_names(config)

    # Order is arbitrary but should include all providers
    assert set(result) == {'lib1', 'lib2', 'local'}


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
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
):
    """Test process_provider handles various error conditions."""
    provider_config = ProviderConfig(cli='mylib-link')

    if exception is None:
        # Success case
        provider_info = ProviderInfo(
            library_name='mylib',
            target_dir=str(tmp_path / '.repolish' / 'mylib'),
            source_dir='/fake/source/mylib',
        )
        _ = mocker.patch(
            'repolish.linker.orchestrator.run_provider_link',
            return_value=provider_info,
        )
        result = process_provider('mylib', provider_config, tmp_path)
        assert result == expected_result
    else:
        # Error cases
        _ = mocker.patch(
            'repolish.linker.orchestrator.run_provider_link',
            side_effect=exception,
        )
        result = process_provider('mylib', provider_config, tmp_path)
        assert result == expected_result


def test_process_single_provider_with_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test process_provider creates additional symlinks."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_dir = tmp_path / '.repolish' / 'mylib'
    provider_dir.mkdir(parents=True)
    (provider_dir / 'config.txt').write_text('content')

    provider_config = ProviderConfig(
        cli='mylib-link',
        symlinks=[
            ProviderSymlink(
                source=Path('config.txt'),
                target=Path('config.txt'),
            ),
        ],
    )

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_dir),
        source_dir='/fake/source/mylib',
    )

    _ = mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        return_value=provider_info,
    )
    result = process_provider('mylib', provider_config, tmp_path)

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
    cli: mylib-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(tmp_path / '.repolish' / 'mylib'),
        source_dir='/fake/source/mylib',
    )

    mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        return_value=provider_info,
    )
    result = run(['--config', str(config_file)])

    assert result == 0


def test_run_with_directory_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run processes directory-based providers (no CLI, just directory path)."""
    monkeypatch.chdir(tmp_path)

    # Create provider directory with templates
    provider_dir = tmp_path / 'local_provider'
    provider_dir.mkdir()
    templates_dir = provider_dir / 'templates'
    templates_dir.mkdir()
    (templates_dir / 'repolish.py').write_text('# local provider')
    (templates_dir / 'repolish').mkdir()

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text(f"""
directories:
  - ./templates

providers:
  local:
    directory: {provider_dir}
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    # Mock should NOT be called since directory providers don't use run_provider_link
    mock_run_provider_link = mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
    )

    result = run(['--config', str(config_file)])

    assert result == 0
    # Verify run_provider_link was NOT called for directory-based provider
    mock_run_provider_link.assert_not_called()


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
    cli: lib1-link
  lib2:
    cli: lib2-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    provider_info = ProviderInfo(
        library_name='lib',
        target_dir=str(tmp_path / '.repolish' / 'lib'),
        source_dir='/fake/source/lib',
    )

    mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        return_value=provider_info,
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
    cli: mylib-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
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


def test_save_provider_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that save_provider_info saves provider info correctly."""
    monkeypatch.chdir(tmp_path)

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(tmp_path / '.repolish' / 'mylib'),
        source_dir='/fake/source/mylib',
        templates_dir='templates',
    )

    save_provider_info('mylib', provider_info, tmp_path)

    # Check provider info file saved in .repolish/_/ directory
    info_file = tmp_path / '.repolish' / '_' / 'provider-info.mylib.json'
    assert info_file.exists()

    saved_info = json.loads(info_file.read_text())
    assert saved_info['library_name'] == 'mylib'
    assert saved_info['target_dir'] == str(tmp_path / '.repolish' / 'mylib')
    assert saved_info['templates_dir'] == 'templates'


def test_save_provider_info_with_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that save_provider_info saves alias when name differs from directory."""
    monkeypatch.chdir(tmp_path)

    # Provider is called "base" in config, but target_dir is "codeguide"
    provider_info = ProviderInfo(
        library_name='codeguide',
        target_dir=str(tmp_path / '.repolish' / 'codeguide'),
        source_dir='/fake/source/codeguide',
        templates_dir='templates',
    )

    save_provider_info('base', provider_info, tmp_path)

    # Provider info should be saved in .repolish/_/
    info_file = tmp_path / '.repolish' / '_' / 'provider-info.base.json'
    assert info_file.exists()

    saved_info = json.loads(info_file.read_text())
    assert saved_info['library_name'] == 'codeguide'

    # Alias mapping should also be saved
    alias_file = tmp_path / '.repolish' / '_' / '.all-providers.json'
    assert alias_file.exists()

    aliases = json.loads(alias_file.read_text())
    assert 'aliases' in aliases
    assert aliases['aliases']['base'] == 'codeguide'


def test_run_provider_link_no_extra_save(
    mocker: pytest_mock.MockerFixture,
    tmp_path: Path,
):
    """Test that run_provider_link doesn't save info (that's done by process_provider)."""
    provider_info_data = {
        'library_name': 'mylib',
        'target_dir': '.repolish/mylib',
        'source_dir': '/fake/source/mylib',
        'templates_dir': 'templates',
    }

    mock_run = mocker.patch('subprocess.run')
    mock_info = MagicMock()
    mock_info.stdout = json.dumps(provider_info_data)
    mock_link = MagicMock()
    mock_run.side_effect = [mock_info, mock_link]

    result = run_provider_link('mylib', 'mylib-link')

    assert isinstance(result, ProviderInfo)
    assert result.library_name == 'mylib'
    assert result.target_dir == '.repolish/mylib'
