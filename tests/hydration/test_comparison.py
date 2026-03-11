"""Tests for hydration comparison functionality."""

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from repolish.hydration.comparison import check_generated_output
from repolish.hydration.display import rich_print_diffs
from repolish.loader import Providers, TemplateMapping


def test_mapping_with_none_source_skipped(tmp_path: Path) -> None:
    """Mappings with `None` source are ignored by the comparison step.

    This covers the branch in :func:`~repolish.hydration.comparison._check_file_mappings`
    where the normalized source string is falsey and the entry is skipped. It
    mirrors the behavioural contract of the application module: providers may
    cancel a generated file by returning `None` in the mapping.
    """
    setup_output = tmp_path / 'out'
    (setup_output / 'repolish').mkdir(parents=True)
    # no actual source file is needed for this test

    project_root = tmp_path / 'proj'
    project_root.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={
            'dest.txt': TemplateMapping(source_template=None),
        },
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, project_root)
    assert diffs == [], 'Mapping with None source should be ignored'


def test_check_generated_output_reports_missing_and_diff(
    tmp_path: Path,
) -> None:
    """Test that check_generated_output reports missing files and diffs correctly."""
    # Create setup_output with a file that will differ from project
    setup_output = tmp_path / 'out'
    (setup_output / 'repolish').mkdir(parents=True)
    out_file = setup_output / 'repolish' / 'foo.txt'
    out_file.write_text('new content')

    # create a project file with different content
    project_root = tmp_path / 'proj'
    (project_root).mkdir()
    (project_root / 'foo.txt').write_text('old content')

    providers = Providers(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, project_root)
    # we expect a diff because contents differ
    assert diffs

    # Call without a console so the default Console(force_terminal=True) path is exercised
    rich_print_diffs(diffs)

    # Capture output for each branch and assert expected content appears
    buf = StringIO()
    console = Console(file=buf, highlight=False)

    rich_print_diffs(diffs, console=console)
    output = buf.getvalue()
    assert 'foo.txt' in output  # rule header
    assert 'new content' in output  # diff body

    buf = StringIO()
    console = Console(file=buf, highlight=False)
    rich_print_diffs([('gone.txt', 'MISSING')], console=console)
    output = buf.getvalue()
    assert 'gone.txt' in output
    assert 'MISSING' in output

    buf = StringIO()
    console = Console(file=buf, highlight=False)
    rich_print_diffs(
        [('extra.txt', 'PRESENT_BUT_SHOULD_BE_DELETED')],
        console=console,
    )
    output = buf.getvalue()
    assert 'extra.txt' in output
    assert 'PRESENT_BUT_SHOULD_BE_DELETED' in output


def test_unified_diff_format_has_proper_newlines(tmp_path: Path) -> None:
    r"""Verify that unified diff output has proper newlines between headers.

    This test ensures that the lineterm='\n' fix prevents diff headers
    from running together on one line.
    """
    # Create setup_output with a file
    setup_output = tmp_path / 'out'
    (setup_output / 'repolish').mkdir(parents=True)
    out_file = setup_output / 'repolish' / 'example.txt'
    out_file.write_text('line1\nline2\nline3\n')

    # Create project file with different content
    project_root = tmp_path / 'proj'
    project_root.mkdir()
    proj_file = project_root / 'example.txt'
    proj_file.write_text('line1\nmodified\nline3\n')

    providers = Providers(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, project_root)
    assert len(diffs) == 1
    rel_path, diff_text = diffs[0]
    assert rel_path == 'example.txt'

    # Verify diff has proper structure with newlines
    # Headers should be on separate lines: ---, +++, @@
    assert '\n---' in diff_text or diff_text.startswith('---')
    assert '\n+++' in diff_text
    assert '\n@@' in diff_text

    # Verify headers are NOT on the same line (the bug we fixed)
    lines = diff_text.split('\n')
    # Find the --- line
    from_line_idx = next(i for i, line in enumerate(lines) if line.startswith('---'))
    to_line_idx = next(i for i, line in enumerate(lines) if line.startswith('+++'))
    hunk_line_idx = next(i for i, line in enumerate(lines) if line.startswith('@@'))

    # Headers should be on consecutive separate lines
    assert to_line_idx == from_line_idx + 1
    assert hunk_line_idx == to_line_idx + 1


def test_check_generated_output_handles_prefixed_mapping(
    tmp_path: Path,
) -> None:
    """Mapping prefixed files should be compared using unprefixed destination name."""
    setup_output = tmp_path / 'out'
    (setup_output / 'repolish').mkdir(parents=True)
    # create a prefixed mapping output
    (setup_output / 'repolish' / '_repolish.foo.txt').write_text('mapped')

    project_root = tmp_path / 'proj'
    project_root.mkdir()
    (project_root / 'foo.txt').write_text('other')

    providers = Providers(
        anchors={},
        delete_files=[],
        delete_history={},
        file_mappings={'foo.txt': 'foo.txt'},
    )

    diffs = check_generated_output(setup_output, providers, project_root)
    # diff should refer to the dest path without prefix
    assert any(p == 'foo.txt' for p, _ in diffs), diffs


def test_line_ending_ignored_by_default(tmp_path: Path) -> None:
    """Test that line-ending-only differences (LF vs CRLF) are ignored by default."""
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
    """Test that REPOLISH_PRESERVE_LINE_ENDINGS env var enables line ending detection."""
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
    """Test that identical files produce no diffs even when preserving line endings."""
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
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert not diffs, 'Expected no diffs for identical files even when preserving line endings'


def test_binary_files_identical_produce_no_diff(tmp_path: Path) -> None:
    """Identical binary files that cannot be decoded as UTF-8 should produce no diff."""
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish').mkdir(parents=True)
    binary = b'\x89PNG\r\n\x1a\n\x00\x00\x00\xff\xfe'
    (setup_output / 'repolish' / 'logo.png').write_bytes(binary)

    base_dir = tmp_path / 'base'
    base_dir.mkdir()
    (base_dir / 'logo.png').write_bytes(binary)

    providers = Providers(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert not diffs


def test_binary_files_different_produce_diff_entry(tmp_path: Path) -> None:
    """Differing binary files that cannot be decoded as UTF-8 should appear in diffs."""
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish').mkdir(parents=True)
    (setup_output / 'repolish' / 'logo.png').write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\xff\xfe',
    )

    base_dir = tmp_path / 'base'
    base_dir.mkdir()
    (base_dir / 'logo.png').write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\xaa\xbb',
    )

    providers = Providers(
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert len(diffs) == 1
    assert diffs[0][0] == 'logo.png'


def test_check_skips_paused_regular_file(tmp_path: Path) -> None:
    """A file listed in paused_files produces no diff even when content differs."""
    setup_output = tmp_path / 'out'
    rendered = setup_output / 'repolish' / 'config.toml'
    rendered.parent.mkdir(parents=True)
    rendered.write_text('provider = true')

    base_dir = tmp_path / 'proj'
    base_dir.mkdir()
    (base_dir / 'config.toml').write_text('developer = true')

    providers = Providers(delete_files=[], delete_history={})

    diffs = check_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=frozenset({'config.toml'}),
    )
    assert diffs == []


def test_check_skips_paused_deletion(tmp_path: Path) -> None:
    """A file in both delete_files and paused_files is not reported as PRESENT_BUT_SHOULD_BE_DELETED."""
    setup_output = tmp_path / 'out'
    (setup_output / 'repolish').mkdir(parents=True)

    base_dir = tmp_path / 'proj'
    base_dir.mkdir()
    (base_dir / 'legacy.txt').write_text('old')

    providers = Providers(
        delete_files=[Path('legacy.txt')],
        delete_history={},
    )

    diffs = check_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=frozenset({'legacy.txt'}),
    )
    assert diffs == []
