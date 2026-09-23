"""Summaries: the state package of the apply run.

Layering: once the apply pipeline finishes a session it hands that session
to `SummarySession` (see `contract.py`); this package computes every
disposition (file states, copy pause, stats, promoted rows, post-process
groups) into the typed rows of `rows.py`; a renderer in `repolish.reporting`
turns rows into output. A summary is just a state: no glyphs, styles, or
other display decisions live here.

Public surface: the three derivation entry points, the `SummarySession`
input contract, and the row vocabulary consumers type against. The
helpers behind them (`skip_state`, `copy_row`, `session_groups`, ...)
are test-only seams, imported from submodules.
"""

from repolish.summaries.apply_rows import apply_summary_rows
from repolish.summaries.contract import SummarySession
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
    'post_process_rows',
    'session_label',
]
