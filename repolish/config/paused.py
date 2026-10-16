"""Matching for ``paused_files`` entries.

A ``paused_files`` entry may take three forms:

- **exact path** — ``docs/guide.md`` pauses that file only.
- **directory** — ``.github/workflows`` (trailing slash optional) pauses
  the directory itself and everything under it.
- **glob** — ``*.generated.py`` or ``docs/*.md`` pauses every path that
  matches. Patterns are case-sensitive and ``*`` also crosses directory
  separators (``fnmatch`` semantics), so ``docs/*.md`` covers
  ``docs/a/guide.md`` as well.

The matching itself lives in :func:`repolish.misc.path_entry_matches` —
the same pattern language also scopes ``post_process`` entries, so the one
implementation serves both.

Deliberately exact-only: ``overrides.file_mappings`` and ``overrides.copies``.
Those are permanent and silent, so a broad or mistyped pattern there could
orphan files with no warning. ``paused_files`` is the loud, temporary escape
hatch — the run logs every paused path each time — which is what makes
directories and globs safe here.
"""

from repolish.misc import path_matches_any


def is_paused(
    path: str,
    paused_files: frozenset[str],
) -> bool:
    """Return whether *path* is covered by any ``paused_files`` entry.

    Args:
        path: POSIX destination path relative to the project root.
        paused_files: The raw paused entries from project config.

    Returns:
        True when the path is paused via an exact, directory-prefix, or
        glob match.
    """
    return path_matches_any(path, paused_files)
