import difflib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import IO, TypeVar

from repolish.postprocess.runner import run_post_process

V = TypeVar('V')

__all__ = [
    'build_unified_diff',
    'ensure_dot_repolish',
    'ensure_meta_dir',
    'merge_dicts_first_wins',
    'open_utf8',
    'path_slug',
    'run_post_process',
]


def ensure_dot_repolish(base_dir: Path) -> Path:
    """Create the .repolish directory under base_dir and write a catch-all .gitignore if absent.

    Returns the .repolish Path.
    """
    repolish_dir = base_dir / '.repolish'
    repolish_dir.mkdir(parents=True, exist_ok=True)
    gitignore = repolish_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('*\n!_/\n', encoding='utf-8')
    return repolish_dir


def ensure_meta_dir(base_dir: Path) -> Path:
    """Create the .repolish/_/ meta directory and write a catch-all .gitignore if absent.

    Tools that need access to specific paths inside _/ (e.g. dprint reaching
    _/render/) should negate those paths in their own config.  The .gitignore
    here ignores everything so nothing leaks into version control by default.

    Returns the .repolish/_/ Path.
    """
    meta_dir = base_dir / '.repolish' / '_'
    meta_dir.mkdir(parents=True, exist_ok=True)
    gitignore = meta_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('*\n', encoding='utf-8')
    return meta_dir


def open_utf8(path: Path, mode: str = 'r') -> IO[str]:
    """Open a file with UTF-8 encoding."""
    return path.open(mode, encoding='utf-8')


def path_slug(path: str, sep: str = '--') -> str:
    """Convert a path to a safe filename slug.

    Replaces path separators with a delimiter for use in report filenames,
    debug files, and other contexts where paths need to be embedded in
    filenames.

    Args:
        path: A relative path (e.g., 'some/nested/file.md')
        sep: The separator to use in the slug (default '--')

    Returns:
        A slugified path (e.g., 'some--nested--file.md')
    """
    return path.replace('/', sep).replace('\\', sep)


def build_unified_diff(rel_path: str, current: str, rendered: str) -> str:
    """Build a unified diff between current and rendered text.

    Args:
        rel_path: Path to use in diff headers
        current: Original file content
        rendered: New/expected file content

    Returns:
        Unified diff string
    """
    return ''.join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=rel_path,
            tofile=rel_path,
        ),
    )


def merge_dicts_first_wins(
    dicts: Iterable[Mapping[str, V]],
) -> dict[str, V]:
    """Merge multiple dicts keeping the first occurrence of each key.

    When the same key appears in multiple dicts, the first occurrence wins.
    This is useful for layered configurations where earlier sources take
    precedence.

    Args:
        dicts: Iterable of dicts to merge (e.g., `my_dict.values()`)

    Returns:
        Single merged dict with first-occurrence semantics for duplicate keys

    Example:
        >>> merge_dicts_first_wins([{'a': 1, 'b': 2}, {'b': 3, 'c': 4}])
        {'a': 1, 'b': 2, 'c': 4}
    """
    result: dict[str, V] = {}
    for d in dicts:
        for key, value in d.items():
            result.setdefault(key, value)
    return result
