from dataclasses import dataclass
from pathlib import Path

from hotlog import get_logger

from repolish.exceptions import SymlinkError
from repolish.links.link_ops import read_link_target
from repolish.links.windows_utils import (
    normalize_windows_path,
    supports_symlinks,
)

logger = get_logger(__name__)


@dataclass
class LinkCheckResult:
    """Result of checking if a link or copy needs to be updated.

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


def validate_existing_link(
    target_dir: Path,
    source_dir: Path,
    *,
    force: bool,
) -> LinkCheckResult:
    """Check if an existing link (symlink or junction) points at the correct source.

    Args:
        target_dir: The link to check
        source_dir: The expected source directory
        force: Whether force recreation is requested

    Returns:
        LinkCheckResult with needs_update and is_correct
        - needs_update: True if the link should be recreated
        - is_correct: True if it's already pointing to the correct source
    """
    try:
        current_target = normalize_windows_path(
            read_link_target(target_dir).resolve(),
        )
        expected_target = normalize_windows_path(source_dir.resolve())
        if current_target == expected_target and current_target.exists():
            if force:
                logger.info(
                    'target_correct_but_forcing_recreation',
                    _display_level=1,
                )
                return LinkCheckResult(needs_update=True, is_correct=True)
            logger.info('target_already_correct_skipping', _display_level=1)
            return LinkCheckResult(needs_update=False, is_correct=True)

        logger.info(
            'target_points_to_wrong_location',
            current=str(current_target),
            expected=str(expected_target),
            _display_level=1,
        )
    except (OSError, ValueError):
        # Broken or invalid link
        logger.info('target_is_broken_link', _display_level=1)
    return LinkCheckResult(needs_update=True, is_correct=False)


def check_copy_validity(*, force: bool) -> LinkCheckResult:
    """Check if an existing copied directory needs to be updated.

    Args:
        force: Whether force recreation is requested

    Returns:
        LinkCheckResult with needs_update and is_correct
        - needs_update: True if the copy should be recreated
        - is_correct: True if the copy should be respected (skip recreation)
    """
    # If symlinks are not supported on this system, we can't verify if the copy
    # is up-to-date, so always recreate it to be safe (especially on Windows,
    # where the recreate lands on the junction tier when the filesystem
    # supports it)
    if not supports_symlinks():
        logger.info(
            'copy_exists_recreating_to_ensure_current',
            _display_level=1,
        )
        return LinkCheckResult(needs_update=True, is_correct=False)

    if force:
        logger.info('target_exists_forcing_recreation', _display_level=1)
        return LinkCheckResult(needs_update=True, is_correct=False)

    # On systems with symlink support, if the user created a regular directory
    # instead of a link, respect it and skip unless force=True
    logger.info('target_exists_skipping', _display_level=1)
    return LinkCheckResult(needs_update=False, is_correct=True)
