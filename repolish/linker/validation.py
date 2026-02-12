from dataclasses import dataclass
from pathlib import Path

from hotlog import get_logger

from repolish.exceptions import SymlinkError

from .windows_utils import normalize_windows_path, supports_symlinks

logger = get_logger(__name__)


@dataclass
class SymlinkCheckResult:
    """Result of checking if a symlink or copy needs to be updated.

    Used by validation functions to indicate whether an existing target
    should be kept, updated, or recreated.

    Attributes:
        needs_update: True if the target should be recreated/updated
        is_correct: True if the current target state is acceptable
    """

    needs_update: bool
    is_correct: bool


def validate_source_directory(source_dir: Path) -> None:
    """Validate that source directory exists and is a directory.

    Args:
        source_dir: Path to validate

    Raises:
        FileNotFoundError: If source_dir does not exist
        SymlinkError: If source_dir is not a directory
    """
    if not source_dir.exists():
        logger.error('source_does_not_exist', source=str(source_dir))
        msg = f'Source directory does not exist: {source_dir}'
        raise FileNotFoundError(msg)

    if not source_dir.is_dir():
        logger.error('source_is_not_directory', source=str(source_dir))
        msg = f'Source must be a directory: {source_dir}'
        raise SymlinkError(msg)


def validate_existing_symlink(
    target_dir: Path,
    source_dir: Path,
    *,
    force: bool,
) -> SymlinkCheckResult:
    """Check if an existing symlink is valid and pointing to the correct source.

    Args:
        target_dir: The symlink to check
        source_dir: The expected source directory
        force: Whether force recreation is requested

    Returns:
        SymlinkCheckResult with needs_update and is_correct
        - needs_update: True if the symlink should be recreated
        - is_correct: True if it's already pointing to the correct source
    """
    try:
        current_target = normalize_windows_path(target_dir.readlink().resolve())
        expected_target = normalize_windows_path(source_dir.resolve())
        if current_target == expected_target and current_target.exists():
            if force:
                logger.info(
                    'target_correct_but_forcing_recreation',
                    _display_level=1,
                )
                return SymlinkCheckResult(needs_update=True, is_correct=True)
            logger.info('target_already_correct_skipping', _display_level=1)
            return SymlinkCheckResult(needs_update=False, is_correct=True)

        logger.info(
            'target_points_to_wrong_location',
            current=str(current_target),
            expected=str(expected_target),
            _display_level=1,
        )
    except (OSError, ValueError):
        # Broken or invalid symlink
        logger.info('target_is_broken_symlink', _display_level=1)
    return SymlinkCheckResult(needs_update=True, is_correct=False)


def check_copy_validity(*, force: bool) -> SymlinkCheckResult:
    """Check if an existing copied directory needs to be updated.

    Args:
        force: Whether force recreation is requested

    Returns:
        SymlinkCheckResult with needs_update and is_correct
        - needs_update: True if the copy should be recreated
        - is_correct: True if the copy should be respected (skip recreation)
    """
    # If symlinks are not supported on this system, we can't verify if the copy
    # is up-to-date, so always recreate it to be safe (especially on Windows)
    if not supports_symlinks():
        logger.info(
            'copy_exists_recreating_to_ensure_current',
            _display_level=1,
        )
        return SymlinkCheckResult(needs_update=True, is_correct=False)

    if force:
        logger.info('target_exists_forcing_recreation', _display_level=1)
        return SymlinkCheckResult(needs_update=True, is_correct=False)

    # On systems with symlink support, if the user created a regular directory
    # instead of a symlink, respect it and skip unless force=True
    logger.info('target_exists_skipping', _display_level=1)
    return SymlinkCheckResult(needs_update=False, is_correct=True)
