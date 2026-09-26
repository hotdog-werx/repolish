"""Derivation for the link summaries: link sections in, rows out.

Two views over the same sections (label + `LinkResult`): the link
summary lists each provider's symlinks, the copy summary lists each
provider's copies with their pause state, so `repolish link` shows what
it did and what it would do. A section whose view is empty contributes
no group, keeping both trees silent when unused. Rendering lives in
`repolish.reporting.leaves`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repolish.summaries.apply_rows import copy_row, symlink_row
from repolish.summaries.rows import ProviderBranch, SessionGroup

if TYPE_CHECKING:
    from collections.abc import Sequence

    from repolish.summaries.contract import LinkResult


def link_symlink_rows(
    sections: Sequence[tuple[str, LinkResult]],
) -> list[SessionGroup]:
    """Build one group per section that resolved symlinks, rows per alias."""
    groups: list[SessionGroup] = []
    for label, result in sections:
        branches = tuple(
            ProviderBranch(
                alias=alias,
                rows=tuple(symlink_row(sl) for sl in symlinks),
            )
            for alias, symlinks in result.symlinks.items()
        )
        if branches:
            groups.append(SessionGroup(title=label, branches=branches))
    return groups


def link_copy_rows(
    sections: Sequence[tuple[str, LinkResult]],
) -> list[SessionGroup]:
    """Build one group per section that resolved copies, rows per alias.

    The pause state comes from the same `copy_row` helper the apply
    summary uses, so both commands report paused and partially paused
    targets identically — including a whole-target pause detected via the
    config's `paused_files` even when nothing was held back.
    """
    groups: list[SessionGroup] = []
    for label, result in sections:
        branches = []
        for alias, copies in result.copies.items():
            held_back = frozenset(result.held_back.get(alias, ()))
            branches.append(
                ProviderBranch(
                    alias=alias,
                    rows=tuple(copy_row(cp, held_back, result.paused_files) for cp in copies),
                ),
            )
        if branches:
            groups.append(SessionGroup(title=label, branches=tuple(branches)))
    return groups
