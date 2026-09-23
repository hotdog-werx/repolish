"""Summaries: the state package of the run reports.

Layering: each finished run hands its contract to this package (see
`contract.py` — `SummarySession` for apply, `PostProcessSession` for
post-process, `LinkResult` for link); this package computes every
disposition (file states, copy pause, stats, promoted rows, post-process
groups, link sections) into the typed rows of `rows.py`; a renderer in
`repolish.reporting` turns rows into output. A summary is just a state:
no glyphs, styles, or other display decisions live here.

Public surface: the derivation entry points, the input contracts, and
the row vocabulary consumers type against. The helpers behind them
(`skip_state`, `copy_row`, `session_groups`, ...) are test-only seams,
imported from submodules.
"""

from repolish.summaries.apply_rows import apply_summary_rows
from repolish.summaries.contract import LinkResult, SummarySession
from repolish.summaries.link_rows import link_copy_rows, link_symlink_rows
from repolish.summaries.post_process import post_process_rows, session_label
from repolish.summaries.rows import (
    STATE_ENUMS,
    AppliedStats,
    CommandRow,
    CommandState,
    CopyRow,
    CopyState,
    FileRow,
    FileState,
    InsertionLine,
    InsertionState,
    PendingStats,
    PromotedRow,
    PromotedState,
    ProviderBranch,
    SessionGroup,
    SymlinkRow,
    ValidatorLine,
    ValidatorState,
)

__all__ = [
    'STATE_ENUMS',
    'AppliedStats',
    'CommandRow',
    'CommandState',
    'CopyRow',
    'CopyState',
    'FileRow',
    'FileState',
    'InsertionLine',
    'InsertionState',
    'LinkResult',
    'PendingStats',
    'PromotedRow',
    'PromotedState',
    'ProviderBranch',
    'SessionGroup',
    'SummarySession',
    'SymlinkRow',
    'ValidatorLine',
    'ValidatorState',
    'apply_summary_rows',
    'link_copy_rows',
    'link_symlink_rows',
    'post_process_rows',
    'session_label',
]
