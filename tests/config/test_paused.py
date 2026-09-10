"""Unit tests for the ``paused_files`` matcher in ``repolish.config.paused``."""

from __future__ import annotations

from repolish.config.paused import is_paused


def test_exact_entry_matches() -> None:
    assert is_paused('docs/guide.md', frozenset({'docs/guide.md'}))


def test_exact_entry_does_not_match_other_paths() -> None:
    assert not is_paused('docs/other.md', frozenset({'docs/guide.md'}))


def test_directory_entry_covers_files_underneath() -> None:
    assert is_paused(
        '.github/workflows/ci.yml',
        frozenset({'.github/workflows'}),
    )


def test_directory_entry_accepts_trailing_slash() -> None:
    assert is_paused(
        '.github/workflows/ci.yml',
        frozenset({'.github/workflows/'}),
    )


def test_directory_entry_covers_nested_directories() -> None:
    assert is_paused('.github/workflows/jobs/build.yml', frozenset({'.github'}))


def test_directory_entry_does_not_match_prefix_siblings() -> None:
    """``.github/workflows`` must not pause ``.github/workflows-extra/x``."""
    assert not is_paused(
        '.github/workflows-extra/x',
        frozenset({'.github/workflows'}),
    )


def test_directory_entry_still_exact_matches_the_same_string() -> None:
    # A non-glob entry is both an exact match and a directory prefix: the
    # exact check runs first, so a path identical to the entry is paused.
    assert is_paused('.github/workflows', frozenset({'.github/workflows'}))


def test_glob_entry_matches() -> None:
    assert is_paused('a.generated.py', frozenset({'*.generated.py'}))


def test_glob_entry_is_case_sensitive() -> None:
    assert not is_paused('README.md', frozenset({'*.MD'}))


def test_glob_entry_is_pattern_matched_not_a_blanket_prefix() -> None:
    """``docs/*.md`` pauses markdown files under ``docs/`` — nothing else."""
    assert is_paused('docs/guide.md', frozenset({'docs/*.md'}))
    assert not is_paused('docs/keep.txt', frozenset({'docs/*.md'}))


def test_glob_entry_star_crosses_directory_separators() -> None:
    """``docs/*`` covers nested paths too, per fnmatch semantics."""
    assert is_paused('docs/x/inner.md', frozenset({'docs/*'}))


def test_question_mark_glob_matches() -> None:
    assert is_paused('v1.md', frozenset({'v?.md'}))


def test_character_class_glob_matches() -> None:
    assert is_paused('v2.md', frozenset({'v[0-9].md'}))


def test_windows_separators_in_entry_are_normalized() -> None:
    """A config typed with backslashes on Windows still matches POSIX paths."""
    assert is_paused('docs/guide.md', frozenset({'docs\\guide.md'}))


def test_windows_directory_entry_covers_files_underneath() -> None:
    assert is_paused(
        '.github/workflows/ci.yml',
        frozenset({'.github\\workflows'}),
    )


def test_windows_directory_entry_accepts_trailing_backslash() -> None:
    assert is_paused('docs/guide.md', frozenset({'docs\\'}))


def test_empty_set_matches_nothing() -> None:
    assert not is_paused('docs/guide.md', frozenset())


def test_mixed_entries_use_first_match() -> None:
    paused = frozenset({'pinned.json', '.github', '*.generated.py'})
    assert is_paused('pinned.json', paused)
    assert is_paused('.github/workflows/ci.yml', paused)
    assert is_paused('src/table.generated.py', paused)
    assert not is_paused('src/main.py', paused)
