import shutil
from pathlib import Path

from hotlog import get_logger

from repolish.links.link_ops import (
    LinkKind,
    create_junction,
    is_junction,
    is_link,
    remove_link,
    supports_junctions,
)
from repolish.links.validation import (
    check_copy_validity,
    validate_existing_link,
    validate_source_directory,
)
from repolish.links.windows_utils import supports_symlinks

logger = get_logger(__name__)


def _remove_target(target: Path) -> None:
    """Remove a target file or directory (link, junction, or copy)."""
    logger.debug('removing_target', target=str(target))

    if is_link(target):
        logger.debug('removing_link')
        remove_link(target)
    elif target.is_dir():
        logger.debug('removing_directory')
        shutil.rmtree(target)
    elif target.is_file():
        logger.debug('removing_file')
        target.unlink()


def _resolve_existing_target(
    target_dir: Path,
    source_dir: Path,
    *,
    force: bool,
) -> LinkKind | None:
    """Determine what action to take for an existing target directory or link.

    Args:
        target_dir: The existing target path
        source_dir: The source directory to link/copy
        force: Whether to force recreation

    Returns:
        The kind of the target that is already in place and respected
        (``'symlink'``, ``'junction'``, or ``'copy'``), or ``None`` when
        the target was removed and the caller should proceed with creation
    """
    if is_link(target_dir):
        result = validate_existing_link(
            target_dir,
            source_dir,
            force=force,
        )
        if not result.needs_update:
            # Already the correct link; report which kind is in place
            return 'junction' if is_junction(target_dir) else 'symlink'

        logger.info(
            'removing_existing_target',
            target=str(target_dir),
            _display_level=1,
        )
        _remove_target(target_dir)
        return None  # Proceed with creation

    # Target is a directory or file (not a link)
    result = check_copy_validity(force=force)
    if result.is_correct:
        return 'copy'  # Skip and report the existing copy

    logger.info(
        'removing_existing_target',
        target=str(target_dir),
        _display_level=1,
    )
    _remove_target(target_dir)
    return None  # Proceed with creation


def _create_link_or_copy_generic(source_path: Path, target_path: Path) -> LinkKind:
    """Create a symlink, junction, or copy from source to target.

    The chain mirrors what the platform allows: a real symlink when the
    process may create one, a junction when Windows blocks symlinks but
    the filesystem takes reparse points, and a copy as the last resort.
    Files skip the junction tier: junctions point at directories only.

    Args:
        source_path: Source file or directory to link/copy from
        target_path: Target location for the link/copy

    Returns:
        The kind of link created, or ``'copy'`` when nothing better was possible
    """
    # Create parent directory
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Real symlinks first: they work everywhere and cross volumes
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
        return 'symlink'

    # Junctions need no privilege and are local-volume only, which is the
    # contract repolish links want anyway
    if supports_junctions() and source_path.is_dir():
        try:
            create_junction(source_path, target_path)
        except OSError as exc:
            logger.warning(
                'junction_creation_failed_falling_back_to_copy',
                target=str(target_path),
                error=str(exc),
            )
        else:
            logger.info(
                'link_created_successfully',
                link_type='junction',
                target=str(target_path),
                _display_level=1,
            )
            return 'junction'

    logger.debug('links_not_supported_copying')
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
    return 'copy'


def link_resources(
    source_dir: Path,
    target_dir: Path,
    *,
    force: bool = False,
) -> LinkKind:
    """Link or copy library resources to target directory.

    Args:
        source_dir: Path to the library's resource directory
        target_dir: Path where resources should be linked (e.g., .repolish/library-name)
        force: If True, always recreate the link/copy even if it exists

    Returns:
        The kind of link created (``'symlink'``, ``'junction'``) or ``'copy'``
        when nothing better was possible

    Raises:
        FileNotFoundError: If source_dir does not exist
        ValueError: If paths are invalid
    """
    # Resolve source but keep target as-is to preserve link detection
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
    if target_dir.exists() or is_link(target_dir):
        result = _resolve_existing_target(target_dir, source_dir, force=force)
        if result is not None:
            return result

    # Create the symlink or copy
    return _create_link_or_copy_generic(source_dir, target_dir)


def create_additional_link(
    resources_dir: Path,
    provider_name: str,
    source: str,
    target: str,
    *,
    force: bool = False,
) -> LinkKind:
    """Create an additional symlink from repo to provider resources.

    Args:
        resources_dir: Absolute path to the provider's resource directory.
        provider_name: Name of the provider (alias from repolish.yaml)
        source: Path relative to the provider's resources (e.g., 'configs/.editorconfig')
        target: Path relative to repo root (e.g., '.editorconfig')
        force: If True, remove existing target before creating link

    Returns:
        The kind of link created (``'symlink'``, ``'junction'``) or ``'copy'``
        when nothing better was possible
    """
    source_path = resources_dir / source
    target_path = Path(target)

    logger.info(
        'creating_additional_link',
        provider=provider_name,
        source=source,
        target=target,
        _display_level=1,
    )

    # Validate source exists
    if not source_path.exists():
        logger.error('source_does_not_exist', source=str(source_path))
        msg = f'Source does not exist: {source_path}'
        raise FileNotFoundError(msg)

    # Handle existing target. A *broken* link reports as absent to
    # Path.exists() (it follows the link), so it must be checked explicitly —
    # and since a dangling link holds no user data, it is always replaced
    # instead of erroring, mirroring link_resources.
    if is_link(target_path) and not target_path.exists():
        logger.info(
            'removing_broken_link',
            target=str(target_path),
            _display_level=1,
        )
        remove_link(target_path)
    elif target_path.exists():
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
