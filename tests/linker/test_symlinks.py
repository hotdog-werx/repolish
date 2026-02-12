import shutil
from pathlib import Path

import pytest
import pytest_mock
from pytest_mock import MockerFixture

from repolish.config.models import ProviderInfo
from repolish.linker.symlinks import (
    create_additional_link,
    link_resources,
)
from repolish.linker.windows_utils import supports_symlinks


def assert_symlink_with_file(target: Path, filename: str, content: str):
    """Assert that target is a symlink, exists, and contains the expected file with content."""
    assert target.is_symlink(), f'Expected {target} to be a symlink'
    assert target.exists(), f'Expected {target} to exist'
    assert (target / filename).read_text() == content


def assert_copied_directory(target: Path):
    """Assert that target is a copied directory (not symlink)."""
    assert target.exists(), f'Expected {target} to exist'
    assert target.is_dir(), f'Expected {target} to be a directory'
    assert not target.is_symlink(), f'Expected {target} to not be a symlink'


def assert_copy_with_file(target: Path, filename: str, content: str):
    """Assert that target is a copy (not symlink), exists, and contains the expected file with content."""
    assert_copied_directory(target)
    assert (target / filename).read_text() == content


def create_test_dir(tmp_path: Path, name: str, filename: str = 'content.txt', content: str = 'content') -> Path:
    """Create a test directory with a file inside."""
    test_dir = tmp_path / name
    test_dir.mkdir()
    (test_dir / filename).write_text(content)
    return test_dir


def mock_no_symlinks(mocker: pytest_mock.MockerFixture):
    """Mock supports_symlinks to return False for both linker modules."""
    mocker.patch('repolish.linker.symlinks.supports_symlinks', return_value=False)
    mocker.patch('repolish.linker.validation.supports_symlinks', return_value=False)


def test_link_resources_creates_symlink(tmp_path: Path, source_with_file: Path):
    """Test link_resources creates a symlink when supported."""
    target = tmp_path / 'target'

    result = link_resources(source_with_file, target)

    # On systems with symlink support, should return True
    # On systems without, should return False
    assert isinstance(result, bool)
    assert target.exists()

    # Verify the content is accessible
    assert (target / 'file.txt').read_text() == 'content'


def test_link_resources_skips_existing_target_without_force(
    tmp_path: Path,
    source_with_file: Path,
):
    """Test link_resources skips linking when target exists and force=False."""
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'existing.txt').write_text('existing')

    # Should skip and return whether target is a symlink
    result = link_resources(source_with_file, target, force=False)

    assert isinstance(result, bool)
    # Target should still exist with original content
    assert (target / 'existing.txt').exists()
    assert (target / 'existing.txt').read_text() == 'existing'


def test_link_resources_replaces_existing_target_with_force(
    tmp_path: Path,
    source_with_file: Path,
):
    """Test link_resources replaces target when force=True."""
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'old.txt').write_text('old')

    result = link_resources(source_with_file, target, force=True)

    assert isinstance(result, bool)
    assert target.exists()
    # Old file should be gone, new file should be accessible
    assert not (target / 'old.txt').exists()
    assert (target / 'file.txt').read_text() == 'content'


def test_link_resources_creates_parent_directories(
    tmp_path: Path,
    source_with_file: Path,
):
    """Test link_resources creates parent directories if needed."""
    target = tmp_path / 'nested' / 'deep' / 'target'

    result = link_resources(source_with_file, target)

    assert isinstance(result, bool)
    assert target.exists()
    assert (target / 'file.txt').read_text() == 'content'


def test_link_resources_copies_when_symlinks_not_supported(
    mocker: MockerFixture,
    tmp_path: Path,
):
    """Test link_resources falls back to copying when symlinks aren't supported."""
    mock_no_symlinks(mocker)

    source = tmp_path / 'source'
    source.mkdir()
    (source / 'file.txt').write_text('content')

    target = tmp_path / 'target'

    result = link_resources(source, target)

    assert result is False  # Should return False when copying
    assert_copy_with_file(target, 'file.txt', 'content')


def test_create_additional_link_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_resources_setup: Path,
    basic_provider_info: ProviderInfo,
):
    """Test create_additional_link creates a link for a file."""
    monkeypatch.chdir(tmp_path)

    # Setup config file
    config_dir = provider_resources_setup / 'configs'
    config_dir.mkdir()
    config_file = config_dir / '.editorconfig'
    config_file.write_text('root = true')

    result = create_additional_link(
        provider_info=basic_provider_info,
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
    provider_resources_setup: Path,
    basic_provider_info: ProviderInfo,
):
    """Test create_additional_link creates a link for a directory."""
    monkeypatch.chdir(tmp_path)

    # Setup docs directory
    docs_dir = provider_resources_setup / 'docs'
    docs_dir.mkdir()
    (docs_dir / 'README.md').write_text('# Docs')

    result = create_additional_link(
        provider_info=basic_provider_info,
        provider_name='mylib',
        source='docs',
        target='documentation',
    )

    assert isinstance(result, bool)
    target_path = tmp_path / 'documentation'
    assert target_path.exists()
    assert (target_path / 'README.md').read_text() == '# Docs'


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
    mock_no_symlinks(mocker)

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
    mock_no_symlinks(mocker)

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
    assert_copied_directory(target_path)
    assert (target_path / 'file1.txt').read_text() == 'content1'
    assert (target_path / 'file2.txt').read_text() == 'content2'


def test_link_resources_with_broken_symlink_target(tmp_path: Path):
    """Test link_resources when target is a broken symlink.

    This reproduces a crash scenario when updating packages that changed location:
    1. Create symlink from fileA to fileB
    2. Delete fileA (source) - symlink becomes broken
    3. Create fileC and try to create symlink from fileC to fileB

    In some cases this can cause a crash when trying to overwrite the broken symlink.
    """
    # Skip test if symlinks are not supported
    if not supports_symlinks():
        pytest.skip('Symlinks not supported on this system')

    # Step 1: Create initial source and target, create symlink
    file_a = create_test_dir(tmp_path, 'fileA', content='from A')

    file_b = tmp_path / 'fileB'

    # Create symlink from fileA to fileB
    result = link_resources(file_a, file_b, force=False)
    assert result is True  # Should return True for symlink
    assert_symlink_with_file(file_b, 'content.txt', 'from A')

    # Step 2: Delete the source (fileA) - now fileB is a broken symlink

    shutil.rmtree(file_a)
    assert not file_a.exists()
    assert file_b.is_symlink()  # Still a symlink
    assert not file_b.exists()  # But broken (points to non-existent target)

    # Step 3: Create fileC and try to create symlink from fileC to fileB
    file_c = create_test_dir(tmp_path, 'fileC', content='from C')

    # This should successfully replace the broken symlink with a new one
    result = link_resources(file_c, file_b, force=True)
    assert result is True
    assert_symlink_with_file(file_b, 'content.txt', 'from C')


def test_link_resources_replace_valid_symlink(tmp_path: Path):
    """Test replacing a valid symlink with a new one pointing to different location.

    This tests whether we can change where a symlink points:
    1. Create symlink from fileA to fileB
    2. Create fileC and try to create symlink from fileC to fileB

    Expected behavior:
    - Without force: If fileB points to wrong location, it gets fixed automatically
    - With force: fileB gets recreated even if already correct
    """
    # Skip test if symlinks are not supported
    if not supports_symlinks():
        pytest.skip('Symlinks not supported on this system')

    # Step 1: Create initial source and target, create symlink
    file_a = create_test_dir(tmp_path, 'fileA', content='from A')

    file_b = tmp_path / 'fileB'

    # Create symlink from fileA to fileB
    result = link_resources(file_a, file_b, force=False)
    assert result is True  # Should return True for symlink
    assert_symlink_with_file(file_b, 'content.txt', 'from A')

    # Step 2: Create fileC and try to create symlink from fileC to fileB
    file_c = create_test_dir(tmp_path, 'fileC', content='from C')

    # Without force, should detect wrong target and fix it automatically
    result = link_resources(file_c, file_b, force=False)
    assert result is True  # Returns True for symlink
    assert_symlink_with_file(file_b, 'content.txt', 'from C')

    # Step 3: Try again with same source - should skip since it's already correct
    result = link_resources(file_c, file_b, force=False)
    assert result is True
    assert_symlink_with_file(file_b, 'content.txt', 'from C')

    # Step 4: With force=True, should recreate even though already correct
    result = link_resources(file_c, file_b, force=True)
    assert result is True
    assert_symlink_with_file(file_b, 'content.txt', 'from C')


def test_link_resources_handles_symlink_readlink_error(
    mocker: MockerFixture,
    tmp_path: Path,
):
    """Test handling of OSError when reading a symlink.

    This can happen due to permission issues, filesystem corruption, or race conditions.
    """
    # Skip test if symlinks are not supported
    if not supports_symlinks():
        pytest.skip('Symlinks not supported on this system')

    # Create source and symlink
    source = create_test_dir(tmp_path, 'source')

    target = tmp_path / 'target'
    target.symlink_to(source, target_is_directory=True)

    # Mock readlink to raise OSError (simulating permission error or corruption)
    original_readlink = Path.readlink

    def mock_readlink(self: Path) -> Path:
        if self == target:
            msg = 'Permission denied'
            raise OSError(msg)
        return original_readlink(self)

    mocker.patch.object(Path, 'readlink', mock_readlink)

    # Create new source to link
    new_source = create_test_dir(tmp_path, 'new_source', content='new content')

    # Should handle the error gracefully and recreate the symlink
    result = link_resources(new_source, target, force=False)
    assert result is True
    assert target.is_symlink()
    # Verify it now points to new_source (readlink works after recreation)
    mocker.stopall()
    assert target.readlink().resolve() == new_source.resolve()


def test_link_resources_updates_outdated_copy_without_symlinks(
    mocker: MockerFixture,
    tmp_path: Path,
):
    """Test that copies are always updated when symlinks aren't supported.

    On Windows (or when symlinks aren't available), we can't verify if a copied
    directory is up-to-date, so we always recreate it to ensure it's current.
    """
    # Mock to simulate system without symlink support
    mock_no_symlinks(mocker)

    # Step 1: Create initial source and copy it
    source_a = create_test_dir(tmp_path, 'source_a', filename='file.txt', content='version 1')

    target = tmp_path / 'target'

    result = link_resources(source_a, target, force=False)
    assert result is False  # Returns False for copy
    assert_copy_with_file(target, 'file.txt', 'version 1')

    # Step 2: Update source content
    (source_a / 'file.txt').write_text('version 2')
    (source_a / 'new_file.txt').write_text('new content')

    # Step 3: Run link_resources again WITHOUT force
    # Should automatically update because we can't verify if copy is current
    result = link_resources(source_a, target, force=False)
    assert result is False  # Returns False for copy
    assert_copy_with_file(target, 'file.txt', 'version 2')
    assert (target / 'new_file.txt').read_text() == 'new content'  # New file present!

    # Step 4: Verify it recreates every time (no caching on Windows)
    (source_a / 'file.txt').write_text('version 3')
    result = link_resources(source_a, target, force=False)
    assert (target / 'file.txt').read_text() == 'version 3'  # Always fresh!
