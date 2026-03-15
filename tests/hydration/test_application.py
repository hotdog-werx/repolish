"""Tests for hydration application functionality."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from repolish.hydration.application import (
    apply_generated_output,
)
from repolish.loader import Providers, TemplateMapping


def test_apply_creates_file_when_missing(tmp_path: Path):
    """Test that create_only files are created when they don't exist."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # Template provides regular rendered file (already processed by Jinja)
    (repolish_dir / 'src' / 'pkg').mkdir(parents=True)
    (repolish_dir / 'src' / 'pkg' / '__init__.py').write_text(
        '# Initial content',
    )

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # File doesn't exist yet
    providers = Providers(
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


def test_apply_file_mapping_copy(tmp_path: Path):
    """A TemplateMapping source is copied to the project root.

    The mapping source file is expected to be prefixed in the staging area;
    the application step should strip the prefix when copying.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # create the source file that will be mapped (prefixed)
    (repolish_dir / '_repolish.template.txt').write_text('mapped content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={
            'dest.txt': TemplateMapping(source_template='template.txt'),
        },
        delete_history={},
        create_only_files=[],
    )

    apply_generated_output(setup_output, providers, base_dir)

    out_file = base_dir / 'dest.txt'
    assert out_file.exists()
    assert out_file.read_text() == 'mapped content'


def test_apply_file_mapping_copy_without_prefix(tmp_path: Path):
    """Legacy (unprefixed) mapping output is still handled correctly."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    # create an unprefixed source file
    (repolish_dir / 'template.txt').write_text('old mapped')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={
            'dest2.txt': TemplateMapping(source_template='template.txt'),
        },
        delete_history={},
        create_only_files=[],
    )

    apply_generated_output(setup_output, providers, base_dir)

    out_file = base_dir / 'dest2.txt'
    assert out_file.exists()
    assert out_file.read_text() == 'old mapped'


def test_mapping_without_source_logs_warning(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """TemplateMapping with no source should be skipped but warn."""
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={
            'dest.txt': TemplateMapping(source_template=None),
        },
        delete_history={},
        create_only_files=[],
    )

    mock_logger = mocker.patch('repolish.hydration.application.logger')
    apply_generated_output(setup_output, providers, base_dir)
    assert any('mapping_without_source' in str(call) for call in mock_logger.warning.call_args_list)
    # consumer behaviour: file should not be produced
    assert not (base_dir / 'dest.txt').exists()


def test_apply_deletes_directory_in_delete_files(tmp_path: Path) -> None:
    """A directory listed in delete_files is removed via shutil.rmtree.

    Exercises the `target.is_dir()` branch in apply_generated_output.
    """
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish').mkdir(parents=True)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    # Create a directory tree in the project that should be removed
    dir_to_delete = base_dir / 'old_cache'
    (dir_to_delete / 'sub').mkdir(parents=True)
    (dir_to_delete / 'sub' / 'file.txt').write_text('stale')

    providers = Providers(
        delete_files=[Path('old_cache')],
        file_mappings={},
        create_only_files=[],
    )

    apply_generated_output(setup_output, providers, base_dir)

    assert not dir_to_delete.exists()


def test_apply_skips_paused_regular_file(tmp_path: Path) -> None:
    """A file listed in paused_files is not overwritten by apply."""
    setup_output = tmp_path / 'setup-output'
    rendered = setup_output / 'repolish' / 'managed.txt'
    rendered.parent.mkdir(parents=True)
    rendered.write_text('provider version')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    (base_dir / 'managed.txt').write_text('developer version')

    providers = Providers(file_mappings={}, create_only_files=[])

    apply_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=frozenset({'managed.txt'}),
    )

    # developer's local copy must be untouched
    assert (base_dir / 'managed.txt').read_text() == 'developer version'


def test_apply_skips_paused_deletion(tmp_path: Path) -> None:
    """A file listed in both delete_files and paused_files is not deleted."""
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish').mkdir(parents=True)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    kept = base_dir / 'keep_me.txt'
    kept.write_text('important')

    providers = Providers(
        delete_files=[Path('keep_me.txt')],
        file_mappings={},
        create_only_files=[],
    )

    apply_generated_output(
        setup_output,
        providers,
        base_dir,
        paused_files=frozenset({'keep_me.txt'}),
    )

    assert kept.exists()


def test_apply_skips_suppressed_sources(tmp_path: Path) -> None:
    """Files listed in suppressed_sources are not copied even when staged.

    A provider that returns {dest: None} from create_file_mappings is opting
    out of managing that path.  The file may still be present in setup_output
    (it was staged so file_mappings copy logic can reach it) but it must NOT
    be written to the project directory by apply_generated_output.
    """
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish' / '.github' / 'workflows').mkdir(parents=True)
    # file is staged (builder copied it) but provider said None
    suppressed = setup_output / 'repolish' / '.github' / 'workflows' / '_ci-checks.yaml'
    suppressed.write_text('ci content')
    # another regular file that should still be applied
    (setup_output / 'repolish' / 'README.md').write_text('readme')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        file_mappings={},
        create_only_files=[],
        suppressed_sources={'.github/workflows/_ci-checks.yaml'},
    )

    apply_generated_output(setup_output, providers, base_dir)

    # suppressed file must NOT be written to project
    assert not (base_dir / '.github' / 'workflows' / '_ci-checks.yaml').exists()
    # regular file is unaffected
    assert (base_dir / 'README.md').exists()


def test_apply_warns_when_mapped_source_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """apply_generated_output logs a warning and skips the destination.

    Triggered when the source file referenced by a mapping does not exist.
    """
    setup_output = tmp_path / 'setup-output'
    (setup_output / 'repolish').mkdir(parents=True)

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={'config.yml': '_repolish.missing.yml'},
        delete_history={},
    )

    apply_generated_output(setup_output, providers, base_dir)

    captured = capsys.readouterr()
    assert 'file_mapping_source_not_found' in captured.out
    assert '_repolish.missing.yml' in captured.out
    assert not (base_dir / 'config.yml').exists()


def test_apply_skips_regular_file_used_as_mapping_source(tmp_path: Path) -> None:
    """apply_generated_output copies the mapped destination only.

    The source file must not also be copied to its original path when it
    appears as a mapping value.
    """
    setup_output = tmp_path / 'setup-output'
    repolish_dir = setup_output / 'repolish'
    repolish_dir.mkdir(parents=True)
    (repolish_dir / 'template-config.yml').write_text('template content')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()

    providers = Providers(
        anchors={},
        delete_files=[],
        file_mappings={'final-config.yml': 'template-config.yml'},
        delete_history={},
    )

    apply_generated_output(setup_output, providers, base_dir)

    assert (base_dir / 'final-config.yml').read_text() == 'template content'
    assert not (base_dir / 'template-config.yml').exists()
