"""Derivation tests for the insertion catalog: registries in, rows out.

Every test hand-builds a session (a plain structural stand-in satisfying
`InsertionCatalogSession`) with insertion registries of plain functions
and asserts the catalog rows: grouping and ordering, file aggregation,
name qualification, and the two filters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repolish.providers.models import SessionBundle
from repolish.summaries import insertion_function_rows
from repolish.summaries.rows import InsertionCatalogGroup

if TYPE_CHECKING:
    from repolish.summaries.contract import InsertionCatalogSession


def _year(context: object) -> int:  # pragma: no cover - never called
    """Show the current year."""
    return 2026


def _month(context: object) -> int:  # pragma: no cover - never called
    """Show the current month."""
    return 9


def _undocumented(context: object) -> int:  # pragma: no cover - never called
    return 0


class _Session:
    """Structural stand-in for the protocol: providers plus the pid map."""

    def __init__(
        self,
        insertion_sources: dict[str, list[str]],
        file_insertions: dict[str, dict],
        pid_to_alias: dict[str, str] | None = None,
    ) -> None:
        self.providers = SessionBundle(
            insertion_sources=insertion_sources,
            file_insertions=file_insertions,
        )
        self.pid_to_alias = pid_to_alias or {}


def test_groups_and_functions_sort_by_name() -> None:
    session = _Session(
        {'a.md': ['pid-b'], 'b.md': ['pid-a']},
        {
            'a.md': {'zeta': _year},
            'b.md': {'alpha': _month, 'beta': _undocumented},
        },
        {'pid-a': 'alpha', 'pid-b': 'beta'},
    )
    # The witness assignment doubles as the protocol check: ty fails the
    # build if the stand-in stops satisfying InsertionCatalogSession.
    witness: InsertionCatalogSession = session
    groups = insertion_function_rows(witness)
    assert [g.provider for g in groups] == ['alpha', 'beta']
    assert [f.name for f in groups[0].functions] == ['alpha', 'beta']
    assert groups[1].functions[0].name == 'zeta'


def test_files_aggregate_across_registrations() -> None:
    """One function registered for one provider over several files.

    lists every file, sorted, on a single row.
    """
    session = _Session(
        {'b.md': ['pid'], 'a.md': ['pid']},
        {'a.md': {'render': _year}, 'b.md': {'render': _month}},
        {'pid': 'p'},
    )
    (group,) = insertion_function_rows(session)
    (row,) = group.functions
    assert row.files == ('a.md', 'b.md')


def test_summary_comes_from_the_docstring() -> None:
    session = _Session(
        {'a.md': ['pid']},
        {'a.md': {'render': _year}},
        {'pid': 'p'},
    )
    (group,) = insertion_function_rows(session)
    assert group.functions[0].summary == 'Show the current year.'


def test_missing_docstring_gets_a_placeholder() -> None:
    session = _Session(
        {'a.md': ['pid']},
        {'a.md': {'render': _undocumented}},
        {'pid': 'p'},
    )
    (group,) = insertion_function_rows(session)
    assert group.functions[0].summary == 'No docstring provided.'


def test_unqualified_names_belong_to_the_first_provider_only() -> None:
    """An unqualified registry key resolves only for a file's first provider.

    Other providers get nothing from it.
    """
    session = _Session(
        {'a.md': ['pid-first', 'pid-second']},
        {'a.md': {'render': _year}},
        {'pid-first': 'first', 'pid-second': 'second'},
    )
    groups = insertion_function_rows(session)
    assert [g.provider for g in groups] == ['first']


def test_qualified_names_strip_the_provider_prefix() -> None:
    session = _Session(
        {'a.md': ['pid-other']},
        {'a.md': {'second:render': _year}},
        {'pid-other': 'second'},
    )
    (group,) = insertion_function_rows(session)
    assert group.functions[0].name == 'render'


def test_provider_filter_keeps_only_matching_alias() -> None:
    session = _Session(
        {'a.md': ['pid-1'], 'b.md': ['pid-2']},
        {'a.md': {'one': _year}, 'b.md': {'two': _month}},
        {'pid-1': 'alpha', 'pid-2': 'beta'},
    )
    groups = insertion_function_rows(session, provider='beta')
    assert [g.provider for g in groups] == ['beta']
    assert [f.name for f in groups[0].functions] == ['two']


def test_function_filter_matches_the_resolved_name() -> None:
    session = _Session(
        {'a.md': ['pid-1'], 'b.md': ['pid-2']},
        {'a.md': {'one': _year}, 'b.md': {'two': _month}},
        {'pid-1': 'alpha', 'pid-2': 'beta'},
    )
    groups = insertion_function_rows(session, function='two')
    assert [g.provider for g in groups] == ['beta']


def test_filters_that_match_nothing_derive_no_groups() -> None:
    session = _Session(
        {'a.md': ['pid']},
        {'a.md': {'one': _year}},
        {'pid': 'p'},
    )
    assert insertion_function_rows(session, function='nope') == []


def test_empty_registries_derive_no_groups() -> None:
    assert insertion_function_rows(_Session({}, {})) == []


def test_groups_are_frozen_row_data() -> None:
    session = _Session(
        {'a.md': ['pid']},
        {'a.md': {'render': _year}},
        {'pid': 'p'},
    )
    (group,) = insertion_function_rows(session)
    assert isinstance(group, InsertionCatalogGroup)
    assert group == InsertionCatalogGroup(
        provider='p',
        functions=group.functions,
    )
