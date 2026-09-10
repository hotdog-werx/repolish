"""Matching for ``paused_files`` entries.

A ``paused_files`` entry may take three forms:

- **exact path** — ``docs/guide.md`` pauses that file only.
- **directory** — ``.github/workflows`` (trailing slash optional) pauses the
  directory itself and everything under it.
- **glob** — ``*.generated.py`` or ``docs/*.md`` pauses every path that
  matches. Patterns are case-sensitive and ``*`` also crosses directory
  separators (``fnmatch`` semantics), so ``docs/*.md`` covers
  ``docs/a/guide.md`` as well.

Deliberately exact-only: ``overrides.file_mappings`` and ``overrides.copies``.
Those are permanent and silent, so a broad or mistyped pattern there could
orphan files with no warning. ``paused_files`` is the loud, temporary escape
hatch — the run logs every paused path each time — which is what makes
directories and globs safe here.
"""

from fnmatch import fnmatchcase

_GLOB_CHARS = frozenset('*?[')


def is_paused(
    path: str,
    paused_files: frozenset[str],
) -> bool:
    """Return whether *path* is covered by any ``paused_files`` entry.

    Entries are matched after normalizing backslashes to `/` so a config
    typed with Windows separators still works; call sites always pass
    POSIX paths, so only the entry side needs it.

    Args:
        path: POSIX destination path relative to the project root.
        paused_files: The raw paused entries from project config.

    Returns:
        True when the path is paused via an exact, directory-prefix, or
        glob match.
    """
    for raw_entry in paused_files:
        entry = raw_entry.replace('\\', '/')
        if path == entry:
            return True
        if _is_paused_under(path, entry):
            return True
        if _GLOB_CHARS.intersection(entry) and fnmatchcase(path, entry):
            return True
    return False


def _is_paused_under(path: str, entry: str) -> bool:
    """Return whether *path* lives inside the directory named by *entry*.

    A plain (non-glob) entry names a directory subtree: ``.github/workflows``
    pauses ``.github/workflows/ci.yml`` but not ``.github/workflows-extra/x``.
    """
    if _GLOB_CHARS.intersection(entry):
        return False
    return path.startswith(entry.rstrip('/') + '/')
