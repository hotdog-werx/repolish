"""Guarded file reads and mode-preserving writes for marker-driven nodes."""

from pathlib import Path


def read_text_or_none(path: Path) -> str | None:
    """Return the file's UTF-8 text, or ``None`` when unreadable.

    ``None`` covers missing files, non-file paths, OS errors, and content that
    is not valid UTF-8 (e.g. binary), so callers can skip or fall back without
    duplicating the guard. Note this is deliberately *more* tolerant than
    :func:`repolish.directives.files.safe_file_read`, which distinguishes
    missing (empty) from unreadable (raising).
    """
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None


def write_mode_preserved(path: Path, content: str) -> None:
    """Write *content* to *path* (UTF-8), restoring the file's previous mode."""
    mode = path.stat().st_mode
    path.write_text(content, encoding='utf-8')
    path.chmod(mode)
