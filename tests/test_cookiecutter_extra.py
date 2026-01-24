from pathlib import Path

from repolish.cookiecutter import check_generated_output, rich_print_diffs
from repolish.loader import Providers


def test_check_generated_output_reports_missing_and_diff(
    tmp_path: Path,
) -> None:
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
        context={},
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, project_root)
    # we expect a diff because contents differ
    assert diffs
    # Now exercise rich_print_diffs to ensure code path executes (no exception)
    rich_print_diffs(diffs)


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
        context={},
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
