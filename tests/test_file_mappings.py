"""Tests for file_mappings feature (conditional/renamed files)."""

from pathlib import Path
from typing import TYPE_CHECKING, cast

from repolish.cookiecutter import apply_generated_output, check_generated_output
from repolish.loader import (
    Providers,
    create_providers,
)
from repolish.loader.orchestrator import extract_file_mappings_from_module

if TYPE_CHECKING:
    import pytest


def test_extract_file_mappings_from_create_function():
    """Test extracting file_mappings from create_file_mappings() function."""
    module_dict = {
        'create_file_mappings': lambda: {
            '.github/workflows/ci.yml': '_repolish.github.yml',
            'config.toml': '_repolish.config.toml',
        },
    }
    result = extract_file_mappings_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == {
        '.github/workflows/ci.yml': '_repolish.github.yml',
        'config.toml': '_repolish.config.toml',
    }


def test_extract_file_mappings_from_module_variable():
    """Test extracting file_mappings from module-level variable."""
    module_dict = {
        'file_mappings': {
            'README.md': '_repolish.readme.md',
        },
    }
    result = extract_file_mappings_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == {'README.md': '_repolish.readme.md'}


def test_extract_file_mappings_filters_none_values():
    """Test that None values are filtered out (conditional skip)."""
    module_dict = {
        'create_file_mappings': lambda: {
            'included.txt': '_repolish.included.txt',
            'skipped.txt': None,  # Conditional: skip this destination
        },
    }
    result = extract_file_mappings_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == {'included.txt': '_repolish.included.txt'}
    assert 'skipped.txt' not in result


def test_extract_file_mappings_empty_when_missing():
    """Test that empty dict is returned when no file_mappings present."""
    module_dict = {}
    result = extract_file_mappings_from_module(module_dict)
    assert result == {}


def test_apply_generated_output_with_file_mappings(tmp_path: Path):
    """Test that file_mappings are applied correctly."""
    # Setup: create setup_output/repolish with both regular and _repolish. files
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Regular file (should be copied normally)
    (repolish_dir / 'regular.txt').write_text('regular content')

    # Conditional files (should only be copied if in file_mappings)
    (repolish_dir / '_repolish.option-a.yml').write_text('option A')
    (repolish_dir / '_repolish.option-b.yml').write_text('option B')

    # Create providers with file_mappings
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={
            'config.yml': '_repolish.option-a.yml',  # Map to option A
            'subdir/renamed.yml': '_repolish.option-b.yml',  # With subdirectory
        },
        delete_history={},
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Apply
    apply_generated_output(setup_output, providers, base_dir)

    # Verify regular file was copied
    assert (base_dir / 'regular.txt').exists()
    assert (base_dir / 'regular.txt').read_text() == 'regular content'

    # Verify mapped files were copied with rename
    assert (base_dir / 'config.yml').exists()
    assert (base_dir / 'config.yml').read_text() == 'option A'

    assert (base_dir / 'subdir' / 'renamed.yml').exists()
    assert (base_dir / 'subdir' / 'renamed.yml').read_text() == 'option B'

    # Verify _repolish.* files themselves were NOT copied to their original names
    assert not (base_dir / '_repolish.option-a.yml').exists()
    assert not (base_dir / '_repolish.option-b.yml').exists()


def test_apply_skips_repolish_prefix_files_not_in_mappings(tmp_path: Path):
    """Test that _repolish.* files not in mappings are skipped."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Create _repolish. files but don't include them in mappings
    (repolish_dir / '_repolish.unused.txt').write_text('unused')
    (repolish_dir / 'regular.txt').write_text('regular')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},  # Empty mappings
        delete_history={},
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    apply_generated_output(setup_output, providers, base_dir)

    # Regular file should be copied
    assert (base_dir / 'regular.txt').exists()

    # _repolish. file should NOT be copied (not in mappings)
    assert not (base_dir / '_repolish.unused.txt').exists()


def test_check_generated_output_with_file_mappings(tmp_path: Path):
    """Test that check mode reports diffs for mapped files correctly."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Create source file in template
    (repolish_dir / '_repolish.config.yml').write_text('new content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Create destination file with different content
    (base_dir / 'config.yml').write_text('old content')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.config.yml'},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should report a diff for the mapped destination
    assert len(diffs) == 1
    rel, diff_msg = diffs[0]
    assert rel == 'config.yml'
    assert 'old content' in diff_msg
    assert 'new content' in diff_msg


def test_check_reports_missing_mapped_source(tmp_path: Path):
    """Test that check mode reports when mapped source file is missing."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Source file does NOT exist

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.missing.yml'},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'config.yml'
    assert 'MAPPING_SOURCE_MISSING' in msg
    assert '_repolish.missing.yml' in msg


def test_check_reports_missing_mapped_destination(tmp_path: Path):
    """Test that check mode reports when mapped destination is missing."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Source exists
    (repolish_dir / '_repolish.config.yml').write_text('content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    # Destination does NOT exist

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.config.yml'},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'config.yml'
    assert msg == 'MISSING'


def test_file_mappings_merge_across_providers(tmp_path: Path):
    """Test that file_mappings from multiple providers are merged."""
    # Create two template directories
    template_a = tmp_path / 'template_a'
    template_a.mkdir()

    template_b = tmp_path / 'template_b'
    template_b.mkdir()

    # Provider A has one mapping
    (template_a / 'repolish.py').write_text("""
def create_context():
    return {}

def create_file_mappings():
    return {
        "file-a.yml": "_repolish.a.yml"
    }
""")

    # Provider B has another mapping
    (template_b / 'repolish.py').write_text("""
def create_context():
    return {}

def create_file_mappings():
    return {
        "file-b.yml": "_repolish.b.yml"
    }
""")

    providers = create_providers([str(template_a), str(template_b)])

    # Both mappings should be merged
    assert providers.file_mappings == {
        'file-a.yml': '_repolish.a.yml',
        'file-b.yml': '_repolish.b.yml',
    }


def test_file_mappings_later_provider_overrides_earlier(tmp_path: Path):
    """Test that later providers can override earlier file_mappings."""
    template_a = tmp_path / 'template_a'
    template_a.mkdir()

    template_b = tmp_path / 'template_b'
    template_b.mkdir()

    # Both providers map same destination
    (template_a / 'repolish.py').write_text("""
def create_context():
    return {}

def create_file_mappings():
    return {
        "config.yml": "_repolish.option-a.yml"
    }
""")

    (template_b / 'repolish.py').write_text("""
def create_context():
    return {}

def create_file_mappings():
    return {
        "config.yml": "_repolish.option-b.yml"  # Override
    }
""")

    providers = create_providers([str(template_a), str(template_b)])

    # Later provider (template_b) should win
    assert providers.file_mappings == {
        'config.yml': '_repolish.option-b.yml',
    }


def test_check_skips_regular_file_when_used_as_mapping_source(tmp_path: Path):
    """Test that regular files used as mapping sources are skipped in normal check."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Create a regular file (no _repolish. prefix) that's used as a mapping source
    (repolish_dir / 'template-config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Map it to a different destination
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'final-config.yml': 'template-config.yml'},
        delete_history={},
    )

    # Create the destination with matching content
    (base_dir / 'final-config.yml').write_text('template content')

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should not report template-config.yml as missing (it's a source in mappings)
    # Should not report any diffs since final-config.yml matches
    assert len(diffs) == 0


def test_check_no_diff_when_mapped_files_identical(tmp_path: Path):
    """Test that check reports no diff when mapped files are identical."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Create source file
    (repolish_dir / '_repolish.config.yml').write_text('identical content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Create destination with identical content
    (base_dir / 'config.yml').write_text('identical content')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.config.yml'},
        delete_history={},
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should report no diffs since content is identical
    assert len(diffs) == 0


def test_apply_warns_when_mapped_source_missing(
    tmp_path: Path,
    capsys: 'pytest.CaptureFixture[str]',
):
    """Test that apply logs a warning when mapped source file is missing."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Source file does NOT exist

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.missing.yml'},
        delete_history={},
    )

    # Call apply - should log warning
    apply_generated_output(setup_output, providers, base_dir)

    # Capture output (hotlog writes to stdout)
    captured = capsys.readouterr()

    # Should log a warning about missing source
    assert 'file_mapping_source_not_found' in captured.out
    assert '_repolish.missing.yml' in captured.out

    # Destination should not be created
    assert not (base_dir / 'config.yml').exists()


def test_apply_skips_regular_file_when_used_as_mapping_source(tmp_path: Path):
    """Test that regular files used as mapping sources are not copied twice."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Create a regular file (no _repolish. prefix) that's used as a mapping source
    (repolish_dir / 'template-config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Map it to a different destination
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'final-config.yml': 'template-config.yml'},
        delete_history={},
    )

    apply_generated_output(setup_output, providers, base_dir)

    # The mapped destination should exist
    assert (base_dir / 'final-config.yml').exists()
    assert (base_dir / 'final-config.yml').read_text() == 'template content'

    # The source file should NOT be copied to its original location
    # (it's used as a mapping source, so it's skipped in the normal copy loop)
    assert not (base_dir / 'template-config.yml').exists()


def test_nested_conditional_files_in_subdirectories(tmp_path: Path):
    """Test that _repolish.* files work when placed in subdirectories.

    Bug: Currently only works at root level due to startswith() check.
    Files like .github/workflows/_repolish.ci.yml should be treated as conditional.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Create a nested subdirectory with _repolish. files
    workflows_dir = repolish_dir / '.github' / 'workflows'
    workflows_dir.mkdir(parents=True)

    # Create conditional files in subdirectory
    (workflows_dir / '_repolish.github-ci.yml').write_text(
        'github actions content',
    )
    (workflows_dir / '_repolish.gitlab-ci.yml').write_text('gitlab ci content')

    # Create a regular file in the same directory
    (workflows_dir / 'regular.yml').write_text('regular workflow')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Map only one of the conditional files
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={
            '.github/workflows/ci.yml': '.github/workflows/_repolish.github-ci.yml',
        },
        delete_history={},
    )

    apply_generated_output(setup_output, providers, base_dir)

    # The mapped destination should exist
    assert (base_dir / '.github' / 'workflows' / 'ci.yml').exists()
    assert (base_dir / '.github' / 'workflows' / 'ci.yml').read_text() == 'github actions content'

    # The regular file should be copied
    assert (base_dir / '.github' / 'workflows' / 'regular.yml').exists()

    # The _repolish. files themselves should NOT be copied
    # (they are conditional and should only be copied via mappings)
    assert not (base_dir / '.github' / 'workflows' / '_repolish.github-ci.yml').exists()
    assert not (base_dir / '.github' / 'workflows' / '_repolish.gitlab-ci.yml').exists()
