import os
from unittest.mock import patch

from repolish.linker.windows_utils import supports_symlinks


def test_supports_symlinks():
    """Test that supports_symlinks returns a boolean."""
    result = supports_symlinks()
    assert isinstance(result, bool)


def test_supports_symlinks_when_os_lacks_symlink_attribute():
    """Test supports_symlinks when os.symlink attribute doesn't exist."""
    # Mock hasattr to return False for os.symlink
    original_hasattr = hasattr

    def mock_hasattr(obj: object, name: str) -> bool:
        if obj is os and name == 'symlink':
            return False
        return original_hasattr(obj, name)

    with patch('builtins.hasattr', side_effect=mock_hasattr):
        result = supports_symlinks()
        assert result is False
