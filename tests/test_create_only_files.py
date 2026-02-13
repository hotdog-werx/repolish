"""Tests for create_only_files feature (initial scaffolding files)."""

from pathlib import Path
from typing import cast

from repolish.cookiecutter import apply_generated_output, check_generated_output
from repolish.loader import (
    Providers,
    create_providers,
)
from repolish.loader.create_only import extract_create_only_files_from_module


def test_extract_create_only_files_from_create_function():
    """Test extracting create_only_files from create_create_only_files() function."""
    module_dict = {
        'create_create_only_files': lambda: [
            'src/package/__init__.py',
            'config.ini',
        ],
    }
    result = extract_create_only_files_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == [
        'src/package/__init__.py',
        'config.ini',
    ]


def test_extract_create_only_files_from_module_variable():
    """Test extracting create_only_files from module-level variable."""
    module_dict = {
        'create_only_files': [
            'setup.cfg',
            '.gitignore',
        ],
    }
    result = extract_create_only_files_from_module(
        cast('dict[str, object]', module_dict),
    )
    assert result == [
        'setup.cfg',
        '.gitignore',
    ]


def test_extract_create_only_files_empty_when_missing():
    """Test that empty list is returned when no create_only_files present."""
    module_dict = {}
    result = extract_create_only_files_from_module(module_dict)
    assert result == []


def test_apply_regular_files_still_overwritten(tmp_path: Path):
    """Test that regular files (not in create_only_files) are still overwritten."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides both create-only and regular file
    (repolish_dir / '__init__.py').write_text('# Create-only template')
    (repolish_dir / 'config.py').write_text('# Regular template')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Both files exist with user content
    (base_dir / '__init__.py').write_text('# User init')
    (base_dir / 'config.py').write_text('# User config')

    # Only __init__.py is create-only
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('__init__.py')],
    )

    apply_generated_output(setup_output, providers, base_dir)

    # __init__.py should be preserved
    assert (base_dir / '__init__.py').read_text() == '# User init'

    # config.py should be overwritten
    assert (base_dir / 'config.py').read_text() == '# Regular template'


def test_check_skips_create_only_when_exists(tmp_path: Path):
    """Test that check doesn't report diff for create_only files that exist."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides rendered file
    (repolish_dir / 'pkg').mkdir()
    (repolish_dir / 'pkg' / '__init__.py').write_text('# Template')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File exists with different content
    (base_dir / 'pkg').mkdir()
    (base_dir / 'pkg' / '__init__.py').write_text('# User content')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('pkg/__init__.py')],
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should have NO diffs - file exists so it's ignored
    assert len(diffs) == 0


def test_check_reports_create_only_when_missing(tmp_path: Path):
    """Test that check reports MISSING for create_only files that don't exist."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides rendered file
    (repolish_dir / 'pkg').mkdir()
    (repolish_dir / 'pkg' / '__init__.py').write_text('# Template')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    # Directory exists but file doesn't
    (base_dir / 'pkg').mkdir()

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('pkg/__init__.py')],
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should report MISSING since file doesn't exist yet
    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'pkg/__init__.py'
    assert msg == 'MISSING'


def test_check_reports_regular_file_diff(tmp_path: Path):
    """Test that check still reports diffs for regular files."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides both files - one create-only, one regular
    (repolish_dir / '__init__.py').write_text('# Template init')
    (repolish_dir / 'config.py').write_text('# Template config')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Both exist with different content
    (base_dir / '__init__.py').write_text('# User init')
    (base_dir / 'config.py').write_text('# User config')

    # Only __init__.py is create-only
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('__init__.py')],
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should only report diff for config.py (regular file)
    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'config.py'
    assert 'User config' in msg
    assert 'Template config' in msg


def test_create_only_with_file_mappings(tmp_path: Path):
    """Test create_only_files works alongside file_mappings."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides both conditional and regular files
    (repolish_dir / '_repolish.special.py').write_text('# Conditional')
    (repolish_dir / 'regular.py').write_text('# Regular')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Regular file exists (will be preserved by create_only)
    (base_dir / 'regular.py').write_text('# Existing')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={'mapped.py': '_repolish.special.py'},
        delete_history={},
        create_only_files=[Path('regular.py')],  # Regular rendered file
    )

    apply_generated_output(setup_output, providers, base_dir)

    # regular.py should be preserved (exists and is create-only)
    assert (base_dir / 'regular.py').read_text() == '# Existing'

    # mapped.py should be created from file_mappings
    assert (base_dir / 'mapped.py').read_text() == '# Conditional'


def test_create_only_missing_gets_created(tmp_path: Path):
    """Test create_only_files creates file when it doesn't exist."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides rendered file
    (repolish_dir / 'custom').mkdir()
    (repolish_dir / 'custom' / '__init__.py').write_text('# Template init')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File doesn't exist
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('custom/__init__.py')],
    )

    apply_generated_output(setup_output, providers, base_dir)

    # File should be created (doesn't exist, so create-only creates it)
    assert (base_dir / 'custom' / '__init__.py').read_text() == '# Template init'


def test_create_providers_merges_create_only_files(tmp_path: Path):
    """Test that create_only_files are merged across multiple providers."""
    # Create provider modules
    provider1_dir = tmp_path / 'provider1'
    provider1_dir.mkdir()
    (provider1_dir / 'repolish.py').write_text(
        'create_only_files = ["file1.txt", "file2.txt"]',
    )

    provider2_dir = tmp_path / 'provider2'
    provider2_dir.mkdir()
    (provider2_dir / 'repolish.py').write_text(
        'create_only_files = ["file3.txt"]',
    )

    providers = create_providers([str(provider1_dir), str(provider2_dir)])

    # Should have all create_only_files from both providers (lists merged)
    assert len(providers.create_only_files) == 3
    paths = {str(p) for p in providers.create_only_files}
    assert paths == {'file1.txt', 'file2.txt', 'file3.txt'}


def test_create_providers_normalizes_create_only_paths(tmp_path: Path):
    """Test that create_only_files paths are normalized to Path objects."""
    provider_dir = tmp_path / 'provider'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        'create_only_files = ["file.txt", "other.txt"]',
    )

    providers = create_providers([str(provider_dir)])

    # Should be a list of Path objects
    assert isinstance(providers.create_only_files, list)
    assert len(providers.create_only_files) == 2
    paths = {str(p) for p in providers.create_only_files}
    assert paths == {'file.txt', 'other.txt'}


def test_create_only_files_with_delete_files_conflict(tmp_path: Path):
    """Test behavior when file is in both create_only_files and delete_files.

    Delete should win - file marked for deletion shouldn't be preserved.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides rendered file
    (repolish_dir / 'config.yml').write_text('# Template')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File exists
    (base_dir / 'config.yml').write_text('# Existing')

    # File is in both create_only_files and delete_files
    providers = Providers(
        context={},
        anchors={},
        delete_files=[Path('config.yml')],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('config.yml')],
    )

    apply_generated_output(setup_output, providers, base_dir)

    # File should be deleted (delete_files wins)
    assert not (base_dir / 'config.yml').exists()


def test_check_create_only_with_delete_conflict(tmp_path: Path):
    """Test check when file is in both create_only_files and delete_files."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides rendered file
    (repolish_dir / 'config.yml').write_text('# Template')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File exists with different content
    (base_dir / 'config.yml').write_text('# Different')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[Path('config.yml')],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('config.yml')],
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should report PRESENT_BUT_SHOULD_BE_DELETED (delete_files wins)
    assert len(diffs) == 1
    rel, msg = diffs[0]
    assert rel == 'config.yml'
    assert msg == 'PRESENT_BUT_SHOULD_BE_DELETED'


def test_multiple_create_only_files(tmp_path: Path):
    """Test handling multiple create_only files in one operation."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides multiple rendered files
    (repolish_dir / 'src' / 'pkg1').mkdir(parents=True)
    (repolish_dir / 'src' / 'pkg2').mkdir(parents=True)
    (repolish_dir / 'src' / 'pkg3').mkdir(parents=True)
    (repolish_dir / 'src' / 'pkg1' / '__init__.py').write_text('# pkg1')
    (repolish_dir / 'src' / 'pkg2' / '__init__.py').write_text('# pkg2')
    (repolish_dir / 'src' / 'pkg3' / '__init__.py').write_text('# pkg3')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # pkg1 exists (should be preserved)
    (base_dir / 'src' / 'pkg1').mkdir(parents=True)
    (base_dir / 'src' / 'pkg1' / '__init__.py').write_text('# Custom pkg1')

    # pkg2 and pkg3 don't exist (should be created)

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[
            Path('src/pkg1/__init__.py'),
            Path('src/pkg2/__init__.py'),
            Path('src/pkg3/__init__.py'),
        ],
    )

    apply_generated_output(setup_output, providers, base_dir)

    # pkg1 should be preserved
    assert (base_dir / 'src' / 'pkg1' / '__init__.py').read_text() == '# Custom pkg1'

    # pkg2 and pkg3 should be created
    assert (base_dir / 'src' / 'pkg2' / '__init__.py').read_text() == '# pkg2'
    assert (base_dir / 'src' / 'pkg3' / '__init__.py').read_text() == '# pkg3'


def test_create_only_with_file_mapping_skips_when_exists(tmp_path: Path):
    """Test that create_only works with file_mappings - skips when destination exists."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides a _repolish. prefixed file that will be mapped
    (repolish_dir / '_repolish.package_init.py').write_text(
        '# Template __init__',
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Destination file already exists with custom content
    (base_dir / 'src' / 'package_name').mkdir(parents=True)
    (base_dir / 'src' / 'package_name' / '__init__.py').write_text(
        '# Custom __init__',
    )

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={
            'src/package_name/__init__.py': '_repolish.package_init.py',
        },
        delete_history={},
        create_only_files=[
            Path('src/package_name/__init__.py'),
        ],  # Destination path
    )

    apply_generated_output(setup_output, providers, base_dir)

    # File should NOT be overwritten - user content preserved
    assert (base_dir / 'src' / 'package_name' / '__init__.py').read_text() == '# Custom __init__'


def test_create_only_with_file_mapping_creates_when_missing(tmp_path: Path):
    """Test that create_only works with file_mappings - creates when destination missing."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides a _repolish. prefixed file that will be mapped
    (repolish_dir / '_repolish.package_init.py').write_text(
        '# Template __init__',
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Destination file doesn't exist yet

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={
            'src/package_name/__init__.py': '_repolish.package_init.py',
        },
        delete_history={},
        create_only_files=[
            Path('src/package_name/__init__.py'),
        ],  # Destination path
    )

    apply_generated_output(setup_output, providers, base_dir)

    # File should be created from the mapped source
    assert (base_dir / 'src' / 'package_name' / '__init__.py').read_text() == '# Template __init__'


def test_check_skips_create_only_file_mapping_when_exists(tmp_path: Path):
    """Test that check doesn't report diff for create_only file_mappings that exist."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides a _repolish. prefixed file that will be mapped
    (repolish_dir / '_repolish.package_init.py').write_text(
        '# Template __init__',
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Destination file exists with different content
    (base_dir / 'src' / 'package_name').mkdir(parents=True)
    (base_dir / 'src' / 'package_name' / '__init__.py').write_text(
        '# User custom content',
    )

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={
            'src/package_name/__init__.py': '_repolish.package_init.py',
        },
        delete_history={},
        create_only_files=[
            Path('src/package_name/__init__.py'),
        ],  # Destination path
    )

    diffs = check_generated_output(setup_output, providers, base_dir)

    # Should have NO diffs - file exists so it's ignored (create_only)
    assert len(diffs) == 0
