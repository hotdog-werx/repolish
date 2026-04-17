"""Snapshot comparison utility for rendered template output."""

from __future__ import annotations

from pathlib import Path


def assert_snapshots(
    rendered: dict[str, str],
    snapshot_dir: str | Path,
) -> None:
    """Assert rendered output matches golden files in *snapshot_dir*.

    *rendered* is a ``{dest_path: content}`` dict as returned by
    :meth:`ProviderTestBed.render_all`.  Each key is looked up as a file
    under *snapshot_dir*; if the file exists its text is compared to the
    rendered content.

    Missing snapshot files cause an :class:`AssertionError` that includes
    the rendered content so the author can copy it into the snapshot dir.

    Raises:
        AssertionError: When any rendered file does not match its snapshot, or
            when a snapshot file is missing.
    """
    snapshot_dir = Path(snapshot_dir)
    failures: list[str] = []

    for dest_path, content in sorted(rendered.items()):
        snap_file = snapshot_dir / dest_path
        if not snap_file.exists():
            failures.append(
                f'missing snapshot: {snap_file}\n  rendered content ({len(content)} chars):\n{_indent(content)}',
            )
            continue
        expected = snap_file.read_text(encoding='utf-8')
        if content != expected:
            diff = _simple_diff(dest_path, expected, content)
            failures.append(diff)

    if failures:
        msg = f'{len(failures)} snapshot(s) failed:\n\n' + '\n\n'.join(failures)
        raise AssertionError(msg)


def _indent(text: str, prefix: str = '    ') -> str:
    return '\n'.join(prefix + line for line in text.splitlines())


def _simple_diff(path: str, expected: str, actual: str) -> str:
    """Build a human-readable diff between *expected* and *actual*."""
    import difflib  # noqa: PLC0415

    exp_lines = expected.splitlines(keepends=True)
    act_lines = actual.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            exp_lines,
            act_lines,
            fromfile=f'snapshot/{path}',
            tofile=f'rendered/{path}',
        ),
    )
    if diff_lines:
        return ''.join(diff_lines)
    return f'{path}: contents differ (trailing whitespace / newline)'
