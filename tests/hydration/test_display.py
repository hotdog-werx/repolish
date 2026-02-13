"""Tests for hydration display functionality."""

from pathlib import Path

from repolish.hydration.comparison import check_generated_output
from repolish.hydration.display import rich_print_diffs
from repolish.loader import Providers


def test_rich_print_diffs_with_missing_file(tmp_path: Path) -> None:
    """Test that rich_print_diffs handles missing files correctly."""
    # Create setup_output with a file
    setup_output = tmp_path / 'out'
    (setup_output / 'repolish').mkdir(parents=True)
    out_file = setup_output / 'repolish' / 'foo.txt'
    out_file.write_text('content')

    # Project root doesn't have the file
    project_root = tmp_path / 'proj'
    project_root.mkdir()

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, project_root)
    # Should report missing file
    assert diffs
    assert diffs[0][1] == 'MISSING'

    # Test rich_print_diffs doesn't crash
    rich_print_diffs(diffs)
