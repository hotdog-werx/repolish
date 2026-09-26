"""Derivation tests for the link summaries: link sections in, rows out.

`repolish link` hands over one `LinkResult` per config pass, paired with
a section label; these tests assert the rows both views derive — group
and branch order, symlink rows, and the copy pause states, including
the whole-target pause detected via `paused_files` alone (the case the
old inline tree missed).
"""

from pathlib import Path
from typing import cast

from repolish.config.models.provider import ProviderCopy, ProviderSymlink
from repolish.summaries import LinkResult, link_copy_rows, link_symlink_rows
from repolish.summaries.rows import CopyRow, CopyState, SymlinkRow


def _result(
    *,
    symlinks: dict | None = None,
    copies: dict | None = None,
    held_back: dict | None = None,
    paused_files: frozenset[str] = frozenset(),
) -> LinkResult:
    return LinkResult(
        symlinks=symlinks or {},
        copies=copies or {},
        held_back=held_back or {},
        paused_files=paused_files,
    )


def test_symlink_rows_preserve_section_and_alias_order() -> None:
    sl = ProviderSymlink(source=Path('src/a'), target=Path('a'))
    sections = [
        ('Root', _result(symlinks={'p2': [sl], 'p1': [sl]})),
        ('Member: pkg', _result(symlinks={'m1': [sl]})),
    ]
    groups = link_symlink_rows(sections)
    assert [g.title for g in groups] == ['Root', 'Member: pkg']
    assert [b.alias for b in groups[0].branches] == ['p2', 'p1']
    row = groups[1].branches[0].rows[0]
    assert isinstance(row, SymlinkRow)
    # paths pass through in the platform's own separator form, like the apply tree
    assert (row.target, row.source) == ('a', str(Path('src/a')))


def test_symlink_view_skips_sections_without_symlinks() -> None:
    cp = ProviderCopy(source=Path('src/c'), target=Path('c'))
    sections = [('Standalone', _result(copies={'p': [cp]}))]
    assert link_symlink_rows(sections) == []


def test_copy_rows_preserve_section_and_alias_order() -> None:
    cp = ProviderCopy(source=Path('src/c'), target=Path('c'))
    sections = [
        ('Root', _result(copies={'p2': [cp], 'p1': [cp]})),
        ('Member: pkg', _result(copies={'m1': [cp]})),
    ]
    groups = link_copy_rows(sections)
    assert [g.title for g in groups] == ['Root', 'Member: pkg']
    assert [b.alias for b in groups[0].branches] == ['p2', 'p1']


def test_copy_view_skips_sections_without_copies() -> None:
    sl = ProviderSymlink(source=Path('src/a'), target=Path('a'))
    sections = [('Standalone', _result(symlinks={'p': [sl]}))]
    assert link_copy_rows(sections) == []


def test_copy_rows_states_match_the_apply_summary() -> None:
    """Held-back targets pause; deeper held-back paths mark partially."""
    active = ProviderCopy(source=Path('src/c'), target=Path('c'))
    paused = ProviderCopy(source=Path('src/p'), target=Path('p'))
    partial = ProviderCopy(source=Path('src/d'), target=Path('d'))
    sections = [
        (
            'Standalone',
            _result(
                copies={'p': [active, paused, partial]},
                held_back={'p': ['p', 'd/nested/file.txt']},
            ),
        ),
    ]
    rows = cast(
        'tuple[CopyRow, ...]',
        link_copy_rows(sections)[0].branches[0].rows,
    )
    assert [row.state for row in rows] == [
        CopyState.ACTIVE,
        CopyState.PAUSED,
        CopyState.PARTIALLY_PAUSED,
    ]


def test_whole_target_pause_detected_via_paused_files_alone() -> None:
    """A directly-paused target pauses even when nothing was held back.

    The check-mode gap: the old inline tree only looked at held-back
    destinations, so a target paused by config (with an empty held-back
    map) rendered as active.
    """
    copy = ProviderCopy(source=Path('src/p'), target=Path('p'))
    sections = [
        (
            'Standalone',
            _result(copies={'p': [copy]}, paused_files=frozenset({'p'})),
        ),
    ]
    rows = cast(
        'tuple[CopyRow, ...]',
        link_copy_rows(sections)[0].branches[0].rows,
    )
    assert rows[0].state is CopyState.PAUSED


def test_empty_sections_derive_no_groups() -> None:
    assert link_symlink_rows([]) == []
    assert link_copy_rows([]) == []
