import shutil
from pathlib import Path

from hotlog import get_logger

from repolish.config.models import ProviderInfo
from repolish.linker.validation import (
    check_copy_validity,
    validate_existing_symlink,
    validate_source_directory,
)
from repolish.linker.windows_utils import supports_symlinks

logger = get_logger(__name__)


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
        logger.debug(
            'target_does_not_exist',
        )  # pragma: no cover - _remove_target is only called when target exists


def _resolve_existing_target(
    target_dir: Path,
    source_dir: Path,
    *,
    force: bool,
) -> bool | None:
    """Determine what action to take for an existing target directory or symlink.

    Args:
        target_dir: The existing target path
        source_dir: The source directory to link/copy
        force: Whether to force recreation

    Returns:
        True if already a correct symlink (no action needed)
        False if a copy that should be respected (skip operation)
        None if target was removed and caller should proceed with creation
    """
    if target_dir.is_symlink():
        result = validate_existing_symlink(
            target_dir,
            source_dir,
            force=force,
        )
        if not result.needs_update:
            return True  # Already correct symlink

        logger.info(
            'removing_existing_target',
            target=str(target_dir),
            _display_level=1,
        )
        _remove_target(target_dir)
        return None  # Proceed with creation

    # Target is a directory or file (not a symlink)
    result = check_copy_validity(force=force)
    if result.is_correct:
        return False  # Skip and return False because it's a copy

    logger.info(
        'removing_existing_target',
        target=str(target_dir),
        _display_level=1,
    )
    _remove_target(target_dir)
    return None  # Proceed with creation


def _create_link_or_copy_generic(source_path: Path, target_path: Path) -> bool:
    """Create a symlink or copy from source to target (files or directories).

    Args:
        source_path: Source file or directory to link/copy from
        target_path: Target location for the link/copy

    Returns:
        True if symlink was created, False if copy was used
    """
    # Create parent directory
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Create symlink or copy
    if supports_symlinks():
        logger.debug('creating_symlink')
        target_path.symlink_to(
            source_path,
            target_is_directory=source_path.is_dir(),
        )
        logger.info(
            'link_created_successfully',
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
        'copy_created_successfully',
        link_type='copy',
        target=str(target_path),
        _display_level=1,
    )
    return False


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

    validate_source_directory(source_dir)

    # Handle existing target if present
    if target_dir.exists() or target_dir.is_symlink():
        result = _resolve_existing_target(target_dir, source_dir, force=force)
        if result is not None:
            return result

    # Create the symlink or copy
    return _create_link_or_copy_generic(source_dir, target_dir)


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
    return _create_link_or_copy_generic(source_path, target_path)
