import os
import tempfile
from pathlib import Path


def normalize_windows_path(path: Path) -> Path:
    """Normalize Windows extended-length paths by removing the //?/ prefix."""
    path_str = str(path)
    if path_str.startswith('\\\\?\\'):  # pragma: no cover - Windows' retarded extended path prefix
        return Path(path_str[4:])
    return path


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
