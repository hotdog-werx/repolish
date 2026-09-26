# ruff: noqa: INP001, T201 - a standalone report script meant to print
"""Find tests whose product-code coverage is duplicated elsewhere.

Reads the `.coverage` file recorded by the `cov-contexts` mise task (pytest
with `--cov-context=test`, which attributes every executed line to the
test that ran it) and reports redundancy candidates:

- tests covering no product code at all,
- tests whose entire line set is identical to another test's,
- tests whose entire line set is a subset of one other test's,
- how many tests are the sole cover of any line (the ceiling of
  what this analysis can detect: tests inside that number are the
  only ones coverage says anything distinctive about),
- tests outside the library suites whose contribution to the library
  packages is already provided by the library suites alone.

Coverage only says which lines ran. Two tests can execute identical
lines yet assert different behavior, so every candidate is a judgment
call, not a verdict: read the test before deleting it.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from coverage import CoverageData

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO_ROOT = 'repolish/'
LIBRARY_SUITES = ('tests/summaries/', 'tests/reporting/')
LIBRARY_PACKAGES = ('repolish/summaries/', 'repolish/reporting/')

Lines = dict[str, set[tuple[str, int]]]


def per_test_lines(data: CoverageData) -> Lines:
    """Map every test id to the set of (file, line) pairs it executed."""
    lines: Lines = {}
    for filename in data.measured_files():
        for lineno, contexts in data.contexts_by_lineno(filename).items():
            for context in contexts:
                if context.endswith('|run'):
                    test_id = context.removesuffix('|run')
                    lines.setdefault(test_id, set()).add((filename, lineno))
    return lines


def _relative(lines: Lines) -> Lines:
    """Shorten absolute paths to repo-relative product paths."""
    return {
        test_id: {(path.split(REPO_ROOT, 1)[1] if REPO_ROOT in path else path, lineno) for path, lineno in covered}
        for test_id, covered in lines.items()
    }


def _keep(
    covered: set[tuple[str, int]],
    prefixes: Sequence[str],
) -> set[tuple[str, int]]:
    """Return the pairs whose file starts with any of *prefixes*."""
    starts = tuple(prefixes)
    return {(path, lineno) for path, lineno in covered if path.startswith(starts)}


def identical_groups(lines: Lines) -> list[tuple[int, list[str]]]:
    """Group tests whose entire line sets match exactly, with the shared size."""
    by_lines: Mapping[frozenset[tuple[str, int]], list[str]] = {}
    for test_id, covered in lines.items():
        by_lines.setdefault(frozenset(covered), []).append(test_id)
    return [(len(covered), sorted(ids)) for covered, ids in by_lines.items() if len(ids) > 1]


def subset_witnesses(lines: Lines) -> list[tuple[str, str]]:
    """Tests fully covered by a single other test: (redundant, witness)."""
    ordered = sorted(lines.items(), key=lambda item: len(item[1]))
    witnesses = []
    for small_id, small in ordered:
        for big_id, big in ordered:
            if big_id == small_id or len(big) <= len(small):
                continue
            if small < big:
                witnesses.append((small_id, big_id))
                break
    return witnesses


def unique_line_counts(lines: Lines) -> dict[str, int]:
    """Count the lines each test is the only one to cover."""
    times_covered: Counter[tuple[str, int]] = Counter(pair for covered in lines.values() for pair in covered)
    return {test_id: sum(1 for pair in covered if times_covered[pair] == 1) for test_id, covered in lines.items()}


def library_subsumed(lines: Lines) -> list[tuple[str, int]]:
    """Tests outside the library suites that add nothing to the packages.

    The library suites (`tests/summaries`, `tests/reporting`) carry their
    packages to 100% on their own, so any other test whose lines in those
    packages are all covered by them is a removal candidate.
    """
    library_union: set[tuple[str, int]] = set()
    for test_id, covered in lines.items():
        if test_id.startswith(LIBRARY_SUITES):
            library_union.update(_keep(covered, LIBRARY_PACKAGES))
    candidates = []
    for test_id, covered in lines.items():
        contribution = _keep(covered, LIBRARY_PACKAGES)
        outside = contribution and not test_id.startswith(LIBRARY_SUITES)
        if outside and contribution <= library_union:
            candidates.append((test_id, len(contribution)))
    return sorted(candidates, reverse=True, key=lambda item: item[1])


def _print_identical(groups: Sequence[tuple[int, list[str]]]) -> None:
    print(f'identical coverage: {len(groups)} groups')
    for size, ids in sorted(groups, key=lambda group: -group[0]):
        print(f'  {size:5d} lines  {" ".join(ids)}')
    print()


def _print_witnesses(
    witnesses: Sequence[tuple[str, str]],
    lines: Lines,
) -> None:
    print(f'subset of one other test: {len(witnesses)} tests')
    ordered = sorted(witnesses, key=lambda pair: -len(lines[pair[0]]))
    for redundant, witness in ordered:
        small, big = len(lines[redundant]), len(lines[witness])
        print(f'  {redundant} ({small} lines)')
        print(f'    inside {witness} ({big} lines)')
    print()


def _print_library(candidates: Sequence[tuple[str, int]]) -> None:
    print(
        f'library coverage already provided by the library suites: {len(candidates)} tests',
    )
    for test_id, count in candidates:
        print(f'  {test_id} ({count} library lines)')
    print()


def main() -> None:
    """Load the recorded contexts and print the redundancy report."""
    data = CoverageData('.coverage')
    data.read()
    lines = _relative(per_test_lines(data))

    empty = sorted(test_id for test_id, covered in lines.items() if not covered)
    print(f'no product code covered: {len(empty)} tests')
    for test_id in empty:
        print(f'  {test_id}')
    print()

    _print_identical(identical_groups(lines))
    _print_witnesses(subset_witnesses(lines), lines)
    _print_library(library_subsumed(lines))

    unique = unique_line_counts(lines)
    distinctive = sum(1 for count in unique.values() if count)
    print(
        f'sole cover of at least one line: {distinctive} of {len(unique)} tests',
    )
    for test_id, count in sorted(unique.items(), key=lambda item: -item[1])[:25]:
        print(f'  {count:4d} unique lines  {test_id}')


if __name__ == '__main__':
    main()
