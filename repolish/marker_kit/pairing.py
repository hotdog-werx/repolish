"""Pair regions between two versions of the same file.

Both keep-block reconciliation (preprocessors) and insertion-marker adoption
(insertions) answer the same question: *which region in the local file
corresponds to which region in the template/rendered file?* The shared rule:
match by key in occurrence order — the template decides *where* regions live,
the local file decides *how* each is filled.
"""

from collections.abc import Callable, Iterable
from typing import Generic, TypeVar

A = TypeVar('A')
B = TypeVar('B')
K = TypeVar('K')


def pair_in_occurrence_order(
    primary: Iterable[A],
    secondary: Iterable[B],
    *,
    key: Callable[[A | B], K],
) -> list[tuple[A, B]]:
    """Pair primary items with secondary items sharing their key, in order.

    Each primary item consumes the next unconsumed secondary item with the
    same key; keys with no remaining counterpart yield no pair. Deterministic
    with respect to both iterables' order.
    """
    grouped: dict[K, list[B]] = {}
    for item in secondary:
        grouped.setdefault(key(item), []).append(item)

    used: dict[K, int] = {}
    pairs: list[tuple[A, B]] = []
    for item in primary:
        k = key(item)
        candidates = grouped.get(k)
        if not candidates:
            continue
        index = used.get(k, 0)
        if index >= len(candidates):
            continue
        used[k] = index + 1
        pairs.append((item, candidates[index]))
    return pairs


class OccurrenceTracker(Generic[K]):
    """Count how many occurrences of each key have been consumed so far.

    Useful when the same marker boundaries appear under several directive
    sites in one pass: each site must resume consuming local regions where the
    previous site left off.
    """

    def __init__(self) -> None:
        self._counts: dict[K, int] = {}

    def take(self, key: K, count: int) -> int:
        """Return the current offset for *key*, then advance it by *count*."""
        start = self._counts.get(key, 0)
        self._counts[key] = start + count
        return start
