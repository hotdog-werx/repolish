from pathlib import Path

import pytest

from repolish.cookiecutter import check_generated_output
from repolish.loader import Providers


def test_line_ending_ignored_by_default(tmp_path: Path) -> None:
    # By default line-ending-only differences (LF vs CRLF) should be ignored.
    setup_output = tmp_path / 'setup-output'
    out_repolish = setup_output / 'repolish'
    out_repolish.mkdir(parents=True)
    out_file = out_repolish / 'a.txt'
    out_file.write_bytes(b'line1\nline2\n')

    base_dir = tmp_path / 'base'
    base_dir.mkdir()
    base_file = base_dir / 'a.txt'
    base_file.write_bytes(b'line1\r\nline2\r\n')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert not diffs, 'Expected no diffs when only line endings differ (default behavior)'


def test_preserve_line_endings_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # When REPOLISH_PRESERVE_LINE_ENDINGS is set, we should detect CRLF vs LF.
    monkeypatch.setenv('REPOLISH_PRESERVE_LINE_ENDINGS', '1')

    setup_output = tmp_path / 'setup-output'
    out_repolish = setup_output / 'repolish'
    out_repolish.mkdir(parents=True)
    out_file = out_repolish / 'a.txt'
    out_file.write_bytes(b'line1\nline2\n')

    base_dir = tmp_path / 'base'
    base_dir.mkdir()
    base_file = base_dir / 'a.txt'
    base_file.write_bytes(b'line1\r\nline2\r\n')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert diffs, 'Expected a diff when preserving line endings'
    _, msg = diffs[0]
    assert '\r\n' in msg


def test_preserve_line_endings_identical_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # When REPOLISH_PRESERVE_LINE_ENDINGS is set and files are byte-identical
    # there should be no diffs.
    monkeypatch.setenv('REPOLISH_PRESERVE_LINE_ENDINGS', '1')

    setup_output = tmp_path / 'setup-output'
    out_repolish = setup_output / 'repolish'
    out_repolish.mkdir(parents=True)
    out_file = out_repolish / 'a.txt'
    # Use CRLF bytes for both files to exercise filecmp fast-path
    out_file.write_bytes(b'line1\r\nline2\r\n')

    base_dir = tmp_path / 'base'
    base_dir.mkdir()
    base_file = base_dir / 'a.txt'
    base_file.write_bytes(b'line1\r\nline2\r\n')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert not diffs, 'Expected no diffs for identical files even when preserving line endings'
