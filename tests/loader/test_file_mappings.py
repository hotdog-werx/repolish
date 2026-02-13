"""Tests for file_mappings extraction functionality."""

from typing import cast

from repolish.loader.orchestrator import extract_file_mappings_from_module


def test_extract_file_mappings_from_create_function():
    """Test extracting file_mappings from create_file_mappings() function."""
    module_dict = {
        'create_file_mappings': lambda: {
            '.github/workflows/ci.yml': '_repolish.github.yml',
            'config.toml': '_repolish.config.toml',
        },
    }
    result = extract_file_mappings_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == {
        '.github/workflows/ci.yml': '_repolish.github.yml',
        'config.toml': '_repolish.config.toml',
    }


def test_extract_file_mappings_from_module_variable():
    """Test extracting file_mappings from module-level variable."""
    module_dict = {
        'file_mappings': {
            'README.md': '_repolish.readme.md',
        },
    }
    result = extract_file_mappings_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == {'README.md': '_repolish.readme.md'}


def test_extract_file_mappings_filters_none_values():
    """Test that None values are filtered out (conditional skip)."""
    module_dict = {
        'create_file_mappings': lambda: {
            'included.txt': '_repolish.included.txt',
            'skipped.txt': None,  # Conditional: skip this destination
        },
    }
    result = extract_file_mappings_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == {'included.txt': '_repolish.included.txt'}
    assert 'skipped.txt' not in result


def test_extract_file_mappings_empty_when_missing():
    """Test that empty dict is returned when no file_mappings present."""
    module_dict = {}
    result = extract_file_mappings_from_module(module_dict)
    assert result == {}
