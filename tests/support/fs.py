"""File-system helpers shared between tests.

This module lives outside of ``conftest`` since it exports plain
functions that can be imported from multiple test modules.  The
``write_module`` helper is used when a test needs to construct a temporary
package tree and then import a file from it; the logic was originally
copied in ``tests/loader/test_module.py`` but is now generic.
"""

from __future__ import annotations

from pathlib import Path


def _touch_init_file(path: Path) -> None:
    """Ensure ``__init__.py`` exists at ``path``.

    This is a tiny helper used by :func:`_touch_init_files` to factor the
    filesystem logic out of the loop.
    """
    init = path / '__init__.py'
    if not init.exists():
        init.write_text('')


def _touch_init_files(base: Path, stop_at: Path | None) -> None:
    """Create ``__init__.py`` files on ``base`` and its ancestors.

    The walk terminates when reaching ``stop_at`` (if provided) or the
    filesystem root to avoid scribbling outside of the test directory.  The
    ``base`` argument should be the resolved path of the directory that will
    contain the module itself.
    """
    while True:
        if stop_at is not None and base == stop_at:
            _touch_init_file(base)
            break
        if base == base.anchor:
            break
        _touch_init_file(base)
        base = base.parent


def write_module(
    path: Path,
    source: str = '',
    *,
    root: Path | None = None,
) -> None:
    """Create a Python module file and make its parents packages.

    ``path`` is the full file path to the module (including ``.py``
    suffix).  Ancestor directories are created using
    ``mkdir(parents=True)`` and any missing ``__init__.py`` files are
    touched so a normal ``import`` will treat the tree as a package.  The
    optional ``root`` parameter bounds the upward walk; when provided, the
    routine stops touching ``__init__.py`` files once it reaches that
    directory (usually ``tmp_path`` in tests) to avoid accidentally
    modifying the filesystem outside the temporary workspace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    base = path.parent.resolve()
    stop_at = root.resolve() if root is not None else None
    _touch_init_files(base, stop_at)
    path.write_text(source)


def module_name_from_path(src: Path, sys_path_entry: Path) -> str:
    """Return the dotted import name for ``src`` relative to ``sys_path_entry``.

    This duplicates the behaviour from the loader's internal helper but
    keeps tests from importing implementation details when they need to
    verify import-name guessing.
    """
    relative = Path(str(src)).relative_to(sys_path_entry)
    return '.'.join(relative.with_suffix('').parts)
