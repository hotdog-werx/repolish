from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from repolish.exceptions import SymlinkError
from repolish.linker.validation import (
    SymlinkCheckResult,
    check_copy_validity,
    validate_existing_symlink,
    validate_source_directory,
)


def test_symlink_check_result_creation():
    """Test creating a SymlinkCheckResult."""
    result = SymlinkCheckResult(needs_update=True, is_correct=False)
    assert result.needs_update is True
    assert result.is_correct is False


def test_validate_source_directory_valid(tmp_path: Path):
    """Test validation of a valid directory."""
    source_dir = tmp_path / 'source'
    source_dir.mkdir()

    # Should not raise
    validate_source_directory(source_dir)


def test_validate_source_directory_nonexistent(tmp_path: Path):
    """Test validation of nonexistent directory."""
    source_dir = tmp_path / 'nonexistent'

    with pytest.raises(
        FileNotFoundError,
        match='Source directory does not exist',
    ):
        validate_source_directory(source_dir)


def test_validate_source_directory_file_instead(tmp_path: Path):
    """Test validation when source is a file instead of directory."""
    source_file = tmp_path / 'source.txt'
    source_file.write_text('content')

    with pytest.raises(SymlinkError, match='Source must be a directory'):
        validate_source_directory(source_file)


@dataclass
class SymlinkValidationCase:
    name: str
    force: bool
    setup_type: str  # 'correct', 'wrong_target', 'broken'
    expected_needs_update: bool
    expected_is_correct: bool


@pytest.mark.parametrize(
    'case',
    [
        SymlinkValidationCase(
            name='no_force_correct_symlink',
            force=False,
            setup_type='correct',
            expected_needs_update=False,
            expected_is_correct=True,
        ),
        SymlinkValidationCase(
            name='with_force_correct_symlink',
            force=True,
            setup_type='correct',
            expected_needs_update=True,
            expected_is_correct=True,
        ),
        SymlinkValidationCase(
            name='wrong_target',
            force=False,
            setup_type='wrong_target',
            expected_needs_update=True,
            expected_is_correct=False,
        ),
        SymlinkValidationCase(
            name='broken_symlink',
            force=False,
            setup_type='broken',
            expected_needs_update=True,
            expected_is_correct=False,
        ),
    ],
    ids=lambda case: case.name,
)
def test_validate_existing_symlink(tmp_path: Path, case: SymlinkValidationCase):
    """Test validate_existing_symlink under different conditions."""
    source_dir = tmp_path / 'source'
    target_dir = tmp_path / 'target'

    if case.setup_type == 'correct':
        source_dir.mkdir()
        target_dir.symlink_to(source_dir)
    elif case.setup_type == 'wrong_target':
        wrong_source = tmp_path / 'wrong'
        source_dir.mkdir()
        wrong_source.mkdir()
        target_dir.symlink_to(wrong_source)
    elif case.setup_type == 'broken':
        source_dir.mkdir()
        target_dir.symlink_to(source_dir)
        source_dir.rmdir()  # Break the symlink

    result = validate_existing_symlink(target_dir, source_dir, force=case.force)
    assert result.needs_update is case.expected_needs_update
    assert result.is_correct is case.expected_is_correct


@dataclass
class CopyValidityCase:
    name: str
    supports_symlinks: bool
    force: bool
    expected_needs_update: bool
    expected_is_correct: bool


@pytest.mark.parametrize(
    'case',
    [
        CopyValidityCase(
            name='no_symlink_support',
            supports_symlinks=False,
            force=False,
            expected_needs_update=True,
            expected_is_correct=False,
        ),
        CopyValidityCase(
            name='with_force',
            supports_symlinks=True,
            force=True,
            expected_needs_update=True,
            expected_is_correct=False,
        ),
        CopyValidityCase(
            name='no_force_symlinks_supported',
            supports_symlinks=True,
            force=False,
            expected_needs_update=False,
            expected_is_correct=True,
        ),
    ],
    ids=lambda case: case.name,
)
def test_check_copy_validity(mocker: MockerFixture, case: CopyValidityCase):
    """Test check_copy_validity under different conditions."""
    mocker.patch(
        'repolish.linker.validation.supports_symlinks',
        return_value=case.supports_symlinks,
    )

    result = check_copy_validity(force=case.force)
    assert result.needs_update is case.expected_needs_update
    assert result.is_correct is case.expected_is_correct
