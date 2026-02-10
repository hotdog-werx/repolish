"""Tests for repolish.linker.symlinks module."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
import pytest_mock
from pytest_mock import MockerFixture

from repolish.config.models import ProviderInfo
from repolish.exceptions import SymlinkError
from repolish.linker.symlinks import (
    _remove_target,
    create_additional_link,
    link_resources,
    supports_symlinks,
)


def test_supports_symlinks():
    """Test that supports_symlinks returns a boolean."""
    result = supports_symlinks()
    assert isinstance(result, bool)


def test_link_resources_creates_symlink(tmp_path: Path):
    """Test link_resources creates a symlink when supported."""
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'file.txt').write_text('content')

    target = tmp_path / 'target'

    result = link_resources(source, target)

    # On systems with symlink support, should return True
    # On systems without, should return False
    assert isinstance(result, bool)
    assert target.exists()

    # Verify the content is accessible
    assert (target / 'file.txt').read_text() == 'content'


def test_link_resources_source_not_exists(tmp_path: Path):
    """Test link_resources raises FileNotFoundError when source doesn't exist."""
    source = tmp_path / 'nonexistent'
    target = tmp_path / 'target'

    with pytest.raises(
        FileNotFoundError,
        match='Source directory does not exist',
    ):
        link_resources(source, target)


def test_link_resources_source_not_directory(tmp_path: Path):
    """Test link_resources raises SymlinkError when source is not a directory."""
    source = tmp_path / 'file.txt'
    source.write_text('content')
    target = tmp_path / 'target'

    with pytest.raises(SymlinkError, match='Source must be a directory'):
        link_resources(source, target)


def test_link_resources_skips_existing_target_without_force(tmp_path: Path):
    """Test link_resources skips linking when target exists and force=False."""
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'file.txt').write_text('original')

    target = tmp_path / 'target'
    target.mkdir()
    (target / 'existing.txt').write_text('existing')

    # Should skip and return whether target is a symlink
    result = link_resources(source, target, force=False)

    assert isinstance(result, bool)
    # Target should still exist with original content
    assert (target / 'existing.txt').exists()
    assert (target / 'existing.txt').read_text() == 'existing'


def test_link_resources_replaces_existing_target_with_force(tmp_path: Path):
    """Test link_resources replaces target when force=True."""
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'file.txt').write_text('new content')

    target = tmp_path / 'target'
    target.mkdir()
    (target / 'old.txt').write_text('old')

    result = link_resources(source, target, force=True)

    assert isinstance(result, bool)
    assert target.exists()
    # Old file should be gone, new file should be accessible
    assert not (target / 'old.txt').exists()
    assert (target / 'file.txt').read_text() == 'new content'


def test_link_resources_creates_parent_directories(tmp_path: Path):
    """Test link_resources creates parent directories if needed."""
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'file.txt').write_text('content')

    target = tmp_path / 'nested' / 'deep' / 'target'

    result = link_resources(source, target)

    assert isinstance(result, bool)
    assert target.exists()
    assert (target / 'file.txt').read_text() == 'content'


def test_link_resources_copies_when_symlinks_not_supported(
    mocker: MockerFixture,
    tmp_path: Path,
):
    """Test link_resources falls back to copying when symlinks aren't supported."""
    mock_supports = mocker.patch('repolish.linker.symlinks.supports_symlinks')
    mock_supports.return_value = False

    source = tmp_path / 'source'
    source.mkdir()
    (source / 'file.txt').write_text('content')

    target = tmp_path / 'target'

    result = link_resources(source, target)

    assert result is False  # Should return False when copying
    assert target.exists()
    assert target.is_dir()
    assert not target.is_symlink()
    assert (target / 'file.txt').read_text() == 'content'


@pytest.mark.parametrize(
    ('target_name', 'setup_target'),
    [
        ('symlink', lambda tmp_path: _setup_symlink_target(tmp_path)),
        ('directory', lambda tmp_path: _setup_directory_target(tmp_path)),
        ('file', lambda tmp_path: _setup_file_target(tmp_path)),
        ('nonexistent', lambda tmp_path: _setup_nonexistent_target(tmp_path)),
    ],
)
def test_remove_target(
    target_name: str,
    setup_target: Callable,
    tmp_path: Path,
):
    """Test _remove_target removes various types of targets."""
    target = setup_target(tmp_path)
    _remove_target(target)
    assert not target.exists()


def _setup_symlink_target(tmp_path: Path) -> Path:
    """Setup a symlink target for testing."""
    source = tmp_path / 'source'
    source.mkdir()
    target = tmp_path / 'link'
    if supports_symlinks():
        target.symlink_to(source, target_is_directory=True)
    return target


def _setup_directory_target(tmp_path: Path) -> Path:
    """Setup a directory target for testing."""
    target = tmp_path / 'dir'
    target.mkdir()
    (target / 'file.txt').write_text('content')
    return target


def _setup_file_target(tmp_path: Path) -> Path:
    """Setup a file target for testing."""
    target = tmp_path / 'file.txt'
    target.write_text('content')
    return target


def _setup_nonexistent_target(tmp_path: Path) -> Path:
    """Setup a nonexistent target for testing."""
    return tmp_path / 'nonexistent'


def test_create_additional_link_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_additional_link creates a link for a file."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)
    config_dir = provider_resources / 'configs'
    config_dir.mkdir()
    config_file = config_dir / '.editorconfig'
    config_file.write_text('root = true')

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    result = create_additional_link(
        provider_info=provider_info,
        provider_name='mylib',
        source='configs/.editorconfig',
        target='.editorconfig',
    )

    assert isinstance(result, bool)
    target_path = tmp_path / '.editorconfig'
    assert target_path.exists()
    assert target_path.read_text() == 'root = true'


def test_create_additional_link_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_additional_link creates a link for a directory."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)
    docs_dir = provider_resources / 'docs'
    docs_dir.mkdir()
    (docs_dir / 'README.md').write_text('# Docs')

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    result = create_additional_link(
        provider_info=provider_info,
        provider_name='mylib',
        source='docs',
        target='documentation',
    )

    assert isinstance(result, bool)
    target_path = tmp_path / 'documentation'
    assert target_path.exists()
    assert (target_path / 'README.md').read_text() == '# Docs'


def test_create_additional_link_source_not_exists(tmp_path: Path):
    """Test create_additional_link raises when source doesn't exist."""
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    with pytest.raises(FileNotFoundError, match='Source does not exist'):
        create_additional_link(
            provider_info=provider_info,
            provider_name='mylib',
            source='nonexistent/file.txt',
            target='target.txt',
        )


def test_create_additional_link_target_exists_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_additional_link raises when target exists and force=False."""
    # Setup provider resources
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)
    config_file = provider_resources / 'config.txt'
    config_file.write_text('new')

    # Create existing target
    target_path = tmp_path / 'config.txt'
    target_path.write_text('existing')

    monkeypatch.chdir(tmp_path)

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    with pytest.raises(FileExistsError, match='Target already exists'):
        create_additional_link(
            provider_info=provider_info,
            provider_name='mylib',
            source='config.txt',
            target='config.txt',
            force=False,
        )


def test_create_additional_link_replaces_target_with_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_additional_link replaces target when force=True."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)
    config_file = provider_resources / 'config.txt'
    config_file.write_text('new content')

    # Create existing target
    target_path = tmp_path / 'config.txt'
    target_path.write_text('old content')

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    result = create_additional_link(
        provider_info=provider_info,
        provider_name='mylib',
        source='config.txt',
        target='config.txt',
        force=True,
    )

    assert isinstance(result, bool)
    assert target_path.exists()
    assert target_path.read_text() == 'new content'


def test_create_additional_link_creates_parent_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_additional_link creates parent directories for target."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)
    config_file = provider_resources / 'config.txt'
    config_file.write_text('content')

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    result = create_additional_link(
        provider_info=provider_info,
        provider_name='mylib',
        source='config.txt',
        target='nested/deep/config.txt',
    )

    assert isinstance(result, bool)
    target_path = tmp_path / 'nested' / 'deep' / 'config.txt'
    assert target_path.exists()
    assert target_path.read_text() == 'content'


def test_create_additional_link_copies_when_no_symlinks(
    mocker: MockerFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_additional_link copies when symlinks aren't supported."""
    monkeypatch.chdir(tmp_path)
    mock_supports = mocker.patch('repolish.linker.symlinks.supports_symlinks')
    mock_supports.return_value = False

    # Setup provider resources
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)
    config_file = provider_resources / 'config.txt'
    config_file.write_text('content')

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    result = create_additional_link(
        provider_info=provider_info,
        provider_name='mylib',
        source='config.txt',
        target='config.txt',
    )

    assert result is False  # Should return False when copying
    target_path = tmp_path / 'config.txt'
    assert target_path.exists()
    assert not target_path.is_symlink()
    assert target_path.read_text() == 'content'


def test_create_additional_link_directory_copies_when_no_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test create_additional_link copies directory when symlinks not supported."""
    provider_resources = tmp_path / '.repolish' / 'mylib'
    provider_resources.mkdir(parents=True)
    configs_dir = provider_resources / 'configs'
    configs_dir.mkdir()
    (configs_dir / 'file1.txt').write_text('content1')
    (configs_dir / 'file2.txt').write_text('content2')

    monkeypatch.chdir(tmp_path)

    # Mock supports_symlinks to return False
    mocker.patch(
        'repolish.linker.symlinks.supports_symlinks',
        return_value=False,
    )

    provider_info = ProviderInfo(
        library_name='mylib',
        target_dir=str(provider_resources),
        source_dir='/fake/source/mylib',
    )

    is_symlink = create_additional_link(
        provider_info=provider_info,
        provider_name='mylib',
        source='configs',
        target='configs',
    )

    # Verify directory was copied (not symlinked)
    assert not is_symlink
    target_path = tmp_path / 'configs'
    assert target_path.exists()
    assert target_path.is_dir()
    assert not target_path.is_symlink()
    assert (target_path / 'file1.txt').read_text() == 'content1'
    assert (target_path / 'file2.txt').read_text() == 'content2'


def test_supports_symlinks_when_os_lacks_symlink_attribute(
    mocker: pytest_mock.MockerFixture,
):
    """Test supports_symlinks returns False when os.symlink doesn't exist."""
    # Mock hasattr to return False for os.symlink
    original_hasattr = hasattr

    def mock_hasattr(obj: object, name: str) -> bool:
        if obj is os and name == 'symlink':
            return False
        return original_hasattr(obj, name)

    mocker.patch('builtins.hasattr', side_effect=mock_hasattr)

    assert supports_symlinks() is False
