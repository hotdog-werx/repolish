"""Integration tests for conflicts between file operations and deletions."""

from pathlib import Path

from repolish.cookiecutter import apply_generated_output, check_generated_output
from repolish.loader import Providers


def test_check_skips_file_when_marked_for_deletion(tmp_path: Path):
    """Test that check doesn't report diff for files marked for deletion.

    Scenario: Template provides config.yml, but user's repolish.yaml
    marks it for deletion. Check should only report PRESENT_BUT_SHOULD_BE_DELETED,
    not also report MISSING or a diff.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides config.yml
    (repolish_dir / 'config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File exists in project with different content
    (base_dir / 'config.yml').write_text('different content')

    # User marks it for deletion
    providers = Providers(
        context={},
        anchors={},
        delete_files=[Path('config.yml')],
        file_mappings={},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should only report PRESENT_BUT_SHOULD_BE_DELETED, not a diff
    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'config.yml'
    assert msg == 'PRESENT_BUT_SHOULD_BE_DELETED'


def test_check_skips_mapped_file_when_marked_for_deletion(tmp_path: Path):
    """Test that check doesn't report diff for mapped files marked for deletion."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides conditional file
    (repolish_dir / '_repolish.config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Destination exists
    (base_dir / 'final-config.yml').write_text('different content')

    # File mapping maps it, but also marked for deletion
    providers = Providers(
        context={},
        anchors={},
        delete_files=[Path('final-config.yml')],
        file_mappings={'final-config.yml': '_repolish.config.yml'},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should only report PRESENT_BUT_SHOULD_BE_DELETED
    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'final-config.yml'
    assert msg == 'PRESENT_BUT_SHOULD_BE_DELETED'


def test_apply_handles_file_then_delete(tmp_path: Path):
    """Test that apply correctly handles file that gets copied then deleted.

    This is the behavior we want: apply should work correctly even if
    a file is both in the template and marked for deletion.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides config.yml
    (repolish_dir / 'config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File exists in project
    (base_dir / 'config.yml').write_text('old content')

    # User marks it for deletion (wins over template)
    providers = Providers(
        context={},
        anchors={},
        delete_files=[Path('config.yml')],
        file_mappings={},
        delete_history={},
    )

    apply_generated_output(setup_output, providers, base_dir)

    # File should be deleted (deletion wins)
    assert not (base_dir / 'config.yml').exists()
