"""Tests for hydration application functionality."""

from pathlib import Path

from repolish.hydration.application import apply_generated_output
from repolish.loader import Providers


def test_apply_creates_file_when_missing(tmp_path: Path):
    """Test that create_only files are created when they don't exist."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides regular rendered file (already processed by cookiecutter)
    (repolish_dir / 'src' / 'pkg').mkdir(parents=True)
    (repolish_dir / 'src' / 'pkg' / '__init__.py').write_text(
        '# Initial content',
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File doesn't exist yet
    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('src/pkg/__init__.py')],
    )

    apply_generated_output(setup_output, providers, base_dir)

    # File should be created
    init_file = base_dir / 'src' / 'pkg' / '__init__.py'
    assert init_file.exists()
    assert init_file.read_text() == '# Initial content'


def test_apply_skips_file_when_exists(tmp_path: Path):
    """Test that create_only files are NOT overwritten if they already exist."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides rendered file with new content
    (repolish_dir / 'src' / 'pkg').mkdir(parents=True)
    (repolish_dir / 'src' / 'pkg' / '__init__.py').write_text(
        '# Template content',
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File already exists with different content
    existing_file = base_dir / 'src' / 'pkg' / '__init__.py'
    existing_file.parent.mkdir(parents=True)
    existing_file.write_text('# Existing content')

    providers = Providers(
        context={},
        anchors={},
        delete_files=[],
        file_mappings={},
        delete_history={},
        create_only_files=[Path('src/pkg/__init__.py')],
    )

    apply_generated_output(setup_output, providers, base_dir)

    # File should NOT be overwritten
    assert existing_file.exists()
    assert existing_file.read_text() == '# Existing content'
