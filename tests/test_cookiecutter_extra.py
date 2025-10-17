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
