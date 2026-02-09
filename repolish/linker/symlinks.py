import os
import shutil
import tempfile
from pathlib import Path

from hotlog import get_logger

from ..config.models import ProviderInfo

logger = get_logger(__name__)


def _cleanup_symlink_test(
    test_link: Path,
    test_path: Path,
) -> None:  # pragma: no cover - Windows-specific
    try:
        if test_link.exists():
            test_link.unlink()
        if test_path.exists():
            test_path.unlink()
    except OSError:
        pass


def _can_create_symlink_in_tmpdir() -> bool:  # pragma: no cover - Windows-specific
    """Attempt to create a symlink in a temp dir. Return True if successful, False otherwise."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / 'symlink_test_target'
        test_link = Path(tmpdir) / 'symlink_test_link'
        test_path.write_text('test')
        try:
            test_link.symlink_to(test_path)
            result = test_link.is_symlink()
        except OSError:
            result = False
        _cleanup_symlink_test(test_link, test_path)
        return result


def supports_symlinks() -> bool:
    """Check if the current system supports symlinks (and has permission)."""
    if not hasattr(os, 'symlink'):
        return False
    if os.name != 'nt':
        return True  # pragma: no cover - Windows will not hit this line
    return _can_create_symlink_in_tmpdir()  # pragma: no cover - Windows-specific


def _remove_target(target: Path) -> None:
    """Remove a target file or directory (symlink or copy)."""
    logger.debug('removing_target', target=str(target))

    if target.is_symlink():
        logger.debug('removing_symlink')
        target.unlink()
    elif target.is_dir():
        logger.debug('removing_directory')
        shutil.rmtree(target)
    elif target.is_file():
        logger.debug('removing_file')
        target.unlink()
    else:
        logger.debug('target_does_not_exist')


def link_resources(
    source_dir: Path,
    target_dir: Path,
    *,
    force: bool = False,
) -> bool:
    """Link or copy library resources to target directory.

    Args:
        source_dir: Path to the library's resource directory
        target_dir: Path where resources should be linked (e.g., .repolish/library-name)
        force: If True, always recreate the link/copy even if it exists

    Returns:
        True if symlink was created, False if copy was used

    Raises:
        FileNotFoundError: If source_dir does not exist
        ValueError: If paths are invalid
    """
    # Resolve source but keep target as-is to preserve symlink detection
    source_dir = source_dir.resolve()
    target_dir = Path(target_dir)

    logger.info(
        'linking_resources',
        source=str(source_dir),
        target=str(target_dir),
        force=force,
        _display_level=1,
    )

    # Validate source
    if not source_dir.exists():
        logger.error('source_does_not_exist', source=str(source_dir))
        msg = f'Source directory does not exist: {source_dir}'
        raise FileNotFoundError(msg)

    if not source_dir.is_dir():
        logger.error('source_is_not_directory', source=str(source_dir))
        msg = f'Source must be a directory: {source_dir}'
        raise ValueError(msg)

    # Skip if target exists and not forcing
    if target_dir.exists() and not force:
        logger.info('target_exists_skipping', _display_level=1)
        return target_dir.is_symlink()

    # Remove existing target if present
    if target_dir.exists():
        logger.info(
            'removing_existing_target',
            target=str(target_dir),
            _display_level=1,
        )
        _remove_target(target_dir)

    # Create parent directory
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    # Create symlink or copy
    if supports_symlinks():
        logger.debug('creating_symlink')
        target_dir.symlink_to(source_dir, target_is_directory=True)
        logger.info('symlink_created_successfully', _display_level=1)
        return True
    logger.debug('symlinks_not_supported_copying_directory')
    shutil.copytree(source_dir, target_dir)
    logger.info('copy_created_successfully', _display_level=1)
    return False


def create_additional_link(
    provider_info: ProviderInfo,
    provider_name: str,
    source: str,
    target: str,
    *,
    force: bool = False,
) -> bool:
    """Create an additional symlink from repo to provider resources.

    This is used by repolish to create additional symlinks defined in repolish.yaml.

    Args:
        provider_info: Provider information containing target_dir and library_name
        provider_name: Name of the provider (used as fallback for library_name)
        source: Path relative to the provider's resources (e.g., 'configs/.editorconfig')
        target: Path relative to repo root (e.g., '.editorconfig')
        force: If True, remove existing target before creating link

    Returns:
        True if symlink was created, False if copy was used

    Example:
        >>> from repolish.config.models import ProviderInfo
        >>> provider_info = ProviderInfo(
        ...     library_name='codeguide',
        ...     target_dir='/path/to/project/.repolish/codeguide'
        ... )
        >>> # Create .editorconfig -> .repolish/codeguide/configs/.editorconfig
        >>> create_additional_link(
        ...     provider_info=provider_info,
        ...     provider_name='codeguide',
        ...     source='configs/.editorconfig',
        ...     target='.editorconfig',
        ... )
    """
    # Resolve paths
    provider_resources = Path(provider_info.target_dir)
    source_path = provider_resources / source
    target_path = Path(target)

    logger.info(
        'creating_additional_link',
        provider=provider_info.library_name or provider_name,
        source=source,
        target=target,
        _display_level=1,
    )

    # Validate source exists
    if not source_path.exists():
        logger.error('source_does_not_exist', source=str(source_path))
        msg = f'Source does not exist: {source_path}'
        raise FileNotFoundError(msg)

    # Handle existing target
    if target_path.exists():
        if force:
            logger.info(
                'removing_existing_target',
                target=str(target_path),
                _display_level=1,
            )
            _remove_target(target_path)
        else:
            logger.error('target_already_exists', target=str(target_path))
            msg = f'Target already exists: {target_path}'
            raise FileExistsError(msg)

    # Create parent directory for target
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Create symlink or copy
    if supports_symlinks():
        logger.debug('creating_symlink')
        target_path.symlink_to(
            source_path,
            target_is_directory=source_path.is_dir(),
        )
        logger.info(
            'additional_link_created',
            link_type='symlink',
            target=str(target_path),
            _display_level=1,
        )
        return True
    logger.debug('symlinks_not_supported_copying')
    if source_path.is_dir():
        shutil.copytree(source_path, target_path)
    else:
        shutil.copy2(source_path, target_path)
    logger.info(
        'additional_link_created',
        link_type='copy',
        target=str(target_path),
        _display_level=1,
    )
    return False
