"""Summaries: the state package of the run reports.

Layering: each finished run hands its contract to this package (the five
in `contract.py`: apply, post-process, link, insertion catalog, lint);
this package computes every disposition (file states, copy pause, stats,
promoted rows, post-process groups, link sections, lint states) into the
typed rows of `rows.py`; a renderer in `repolish.reporting` turns rows
into output. A summary is just a state: no glyphs, styles, or other
display decisions live here.

Public surface: the derivation entry points, the input contracts, and
the row vocabulary consumers type against. The helpers behind them
(`skip_state`, `copy_row`, `session_groups`, ...) are test-only seams,
imported from submodules.
"""

from repolish.summaries.apply_rows import apply_summary_rows
from repolish.summaries.contract import (
    LinkResult,
    LintIssue,
    SummarySession,
    TemplateResult,
)
from repolish.summaries.insertion_rows import insertion_function_rows
from repolish.summaries.link_rows import link_copy_rows, link_symlink_rows
from repolish.summaries.lint_rows import (
    lint_template_rows,
    unmapped_source_rows,
)
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
    InsertionCatalogGroup,
    InsertionFunctionRow,
    InsertionLine,
    InsertionState,
    LintIssueRow,
    LintState,
    LintTemplateRow,
    PendingStats,
    PromotedRow,
    PromotedState,
    ProviderBranch,
    SessionGroup,
    SymlinkRow,
    UnmappedSourceRow,
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
    'InsertionCatalogGroup',
    'InsertionFunctionRow',
    'InsertionLine',
    'InsertionState',
    'LinkResult',
    'LintIssue',
    'LintIssueRow',
    'LintState',
    'LintTemplateRow',
    'PendingStats',
    'PromotedRow',
    'PromotedState',
    'ProviderBranch',
    'SessionGroup',
    'SummarySession',
    'SymlinkRow',
    'TemplateResult',
    'UnmappedSourceRow',
    'ValidatorLine',
    'ValidatorState',
    'apply_summary_rows',
    'insertion_function_rows',
    'link_copy_rows',
    'link_symlink_rows',
    'lint_template_rows',
    'post_process_rows',
    'session_label',
    'unmapped_source_rows',
]
