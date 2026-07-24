"""Snapshot comparison utility for rendered template output."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from textwrap import dedent


def _extract_failed_file(f: str, snapshot_dir: Path) -> str:
    """Extract the failed file path from a failure message."""
    if f.startswith('missing snapshot:'):
        return f.split('\n')[0].replace('missing snapshot: ', '')
    for line in f.split('\n'):
        if line.startswith('--- snapshot/'):
            return str(snapshot_dir / line.replace('--- snapshot/', ''))
    return 'unknown'


def _build_failure_summary(
    failures: list[str],
    snapshot_dir: Path,
) -> str:
    """Build a summary message with full paths to failed snapshot files."""
    failed_files = [_extract_failed_file(f, snapshot_dir) for f in failures]

    summary = f'{len(failures)} snapshot(s) failed:\n'
    summary += '  Failed snapshot files:\n'
    for ff in failed_files:
        summary += f'    - {ff}\n'
    summary += '\n' + '\n\n'.join(failures)
    return summary


def _collect_failures(
    rendered: dict[str, str],
    snapshot_dir: Path,
) -> list[str]:
    """Collect failure messages for snapshot mismatches."""
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
    return failures


def _write_snapshots(
    rendered: dict[str, str],
    snapshot_dir: Path,
) -> None:
    """Write rendered content to snapshot files."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for dest_path, content in sorted(rendered.items()):
        snap_file = snapshot_dir / dest_path
        snap_file.parent.mkdir(parents=True, exist_ok=True)
        snap_file.write_text(content, encoding='utf-8')


def assert_snapshots(
    rendered: dict[str, str],
    snapshot_dir: str | Path,
    *,
    update: bool = False,
) -> None:
    """Assert rendered output matches golden files in *snapshot_dir*.

    *rendered* is a ``{dest_path: content}`` dict as returned by
    :meth:`ProviderTestBed.render_all`.  Each key is looked up as a file
    under *snapshot_dir*; if the file exists its text is compared to the
    rendered content.

    Missing snapshot files cause an :class:`AssertionError` that includes
    the rendered content so the author can copy it into the snapshot dir.

    Args:
        rendered: The rendered output dict to compare.
        snapshot_dir: Directory containing golden snapshot files.
        update: If True, update snapshots instead of failing. Can also be
            set via the ``REPOLISH_UPDATE_SNAPSHOTS=1`` environment variable.

    Raises:
        AssertionError: When any rendered file does not match its snapshot, or
            when a snapshot file is missing (unless ``update`` is True).
    """
    snapshot_dir = Path(snapshot_dir)
    # Check environment variable for update mode
    update_mode = update or os.environ.get(
        'REPOLISH_UPDATE_SNAPSHOTS',
        '0',
    ) in ('1', 'true', 'True')

    if update_mode:
        # Print warning about update mode
        warning_str = dedent(
            f"""
            [WARNING] Snapshot update mode enabled (REPOLISH_UPDATE_SNAPSHOTS=1)
                      Writing snapshots to: {snapshot_dir}
                      Remember to review git changes before committing!
            """,
        )
        sys.stderr.write(warning_str)
        _write_snapshots(rendered, snapshot_dir)
        return

    failures = _collect_failures(rendered, snapshot_dir)
    if failures:
        raise AssertionError(_build_failure_summary(failures, snapshot_dir))


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
