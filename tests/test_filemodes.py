"""Tests for :mod:`repolish.filemodes`, the file-mode authority."""

from pathlib import Path

from repolish.filemodes import (
    MATERIALIZED_MODES,
    FileMode,
    ModeRules,
    fold_mapping,
    posix_dests,
)
from repolish.hydration.mapping_resolution import MappingResolution
from repolish.providers import SessionBundle


def _resolution(
    create_only_dests: set[str],
    delete_dests: set[str],
) -> MappingResolution:
    """A MappingResolution with only the mode fields set."""
    return MappingResolution(
        source_to_dest={},
        dest_to_source={},
        regular_mappings={},
        promoted_mappings={},
        mapped_sources=set(),
        regular_dests=set(),
        promoted_dests=set(),
        paused_dests=frozenset(),
        suppressed_sources=set(),
        create_only_dests=create_only_dests,
        delete_dests=delete_dests,
    )


def test_posix_dests_normalizes_paths() -> None:
    """Destination paths convert once, in POSIX form."""
    assert posix_dests(
        [Path('docs') / 'index.md', Path('old.txt')],
    ) == frozenset({'docs/index.md', 'old.txt'})


def test_mode_rules_from_bundle() -> None:
    """Rules derive from the bundle's declared create-only and delete paths."""
    providers = SessionBundle(
        create_only_files=[Path('docs') / 'index.md'],
        delete_files=[Path('old.txt')],
    )

    rules = ModeRules.from_bundle(providers)

    assert rules.create_only == frozenset({'docs/index.md'})
    assert rules.delete == frozenset({'old.txt'})


def test_mode_rules_from_resolution() -> None:
    """Rules wrap the normalized hydration view without recompute."""
    rules = ModeRules.from_resolution(
        _resolution({'docs/index.md'}, {'old.txt'}),
    )

    assert rules.create_only == frozenset({'docs/index.md'})
    assert rules.delete == frozenset({'old.txt'})


def test_can_write_false_only_for_existing_create_only(tmp_path: Path) -> None:
    """A create-only file is developer-owned from the moment it exists."""
    rules = ModeRules(
        create_only=frozenset({'docs/index.md'}),
        delete=frozenset(),
    )
    existing = tmp_path / 'docs' / 'index.md'
    existing.parent.mkdir()
    existing.write_text('developer edits', encoding='utf-8')

    assert rules.can_write('docs/index.md', tmp_path) is False
    # Missing create-only destinations are created; everything else is writable.
    assert rules.can_write('docs/other.md', tmp_path) is True
    assert rules.can_write('README.md', tmp_path) is True


def test_excluded_from_check_covers_delete_and_existing_create_only(
    tmp_path: Path,
) -> None:
    """Check mode ignores delete-destined and developer-owned paths only."""
    rules = ModeRules(
        create_only=frozenset({'docs/index.md'}),
        delete=frozenset({'old.txt'}),
    )
    existing = tmp_path / 'docs' / 'index.md'
    existing.parent.mkdir()
    existing.write_text('developer edits', encoding='utf-8')

    assert rules.excluded_from_check('old.txt', tmp_path) is True
    assert rules.excluded_from_check('docs/index.md', tmp_path) is True
    assert rules.excluded_from_check('README.md', tmp_path) is False


def test_existing_create_only_returns_only_present_dests(
    tmp_path: Path,
) -> None:
    """Only the create-only destinations that exist are developer-owned."""
    rules = ModeRules(
        create_only=frozenset({'present.md', 'missing.md'}),
        delete=frozenset(),
    )
    (tmp_path / 'present.md').write_text('developer edits', encoding='utf-8')

    assert rules.existing_create_only(tmp_path) == frozenset({'present.md'})


def test_fold_mapping_claims_dests_by_mode() -> None:
    """DELETE and KEEP maintain the delete set; CREATE_ONLY claims its own."""
    delete: set[Path] = {Path('claimed.txt')}
    create_only: set[Path] = set()

    fold_mapping(
        FileMode.DELETE,
        Path('doomed.txt'),
        create_only=create_only,
        delete=delete,
    )
    assert delete == {Path('claimed.txt'), Path('doomed.txt')}

    fold_mapping(
        FileMode.KEEP,
        Path('claimed.txt'),
        create_only=create_only,
        delete=delete,
    )
    assert delete == {Path('doomed.txt')}

    fold_mapping(
        FileMode.CREATE_ONLY,
        Path('docs/index.md'),
        create_only=create_only,
        delete=delete,
    )
    assert create_only == {Path('docs/index.md')}
    assert delete == {Path('doomed.txt')}

    # REGULAR and SUPPRESS make no destination-set claim.
    fold_mapping(
        FileMode.REGULAR,
        Path('plain.txt'),
        create_only=create_only,
        delete=delete,
    )
    fold_mapping(
        FileMode.SUPPRESS,
        Path('hidden.txt'),
        create_only=create_only,
        delete=delete,
    )
    assert create_only == {Path('docs/index.md')}
    assert delete == {Path('doomed.txt')}


def test_materialized_modes_are_the_written_ones() -> None:
    """Only REGULAR and CREATE_ONLY files reach the project tree."""
    assert MATERIALIZED_MODES == (FileMode.REGULAR, FileMode.CREATE_ONLY)
