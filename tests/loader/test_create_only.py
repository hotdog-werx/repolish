"""Tests for create_only_files extraction functionality."""

from typing import cast

from repolish.loader.create_only import extract_create_only_files_from_module


def test_extract_create_only_files_from_create_function():
    """Test extracting create_only_files from create_create_only_files() function."""
    module_dict = {
        'create_create_only_files': lambda: [
            'src/package/__init__.py',
            'config.ini',
        ],
    }
    result = extract_create_only_files_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == [
        'src/package/__init__.py',
        'config.ini',
    ]


def test_extract_create_only_files_from_module_variable():
    """Test extracting create_only_files from module-level variable."""
    module_dict = {
        'create_only_files': [
            'setup.cfg',
            '.gitignore',
        ],
    }
    result = extract_create_only_files_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == [
        'setup.cfg',
        '.gitignore',
    ]


def test_extract_create_only_files_empty_when_missing():
    """Test that empty list is returned when no create_only_files present."""
    module_dict = {}
    result = extract_create_only_files_from_module(module_dict)
    assert result == []
