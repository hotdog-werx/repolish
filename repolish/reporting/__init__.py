"""Summary-tree contract: derivation builds rows, leaves render, render prints."""

from repolish.reporting.nodes import (
    SummaryNode,
    details_link,
    stat_suffix,
)
from repolish.reporting.post_process import post_process_nodes, session_label
from repolish.reporting.render import (
    print_completed_footer,
    print_run_header,
    print_summary_trees,
    render_summary_tree,
)
from repolish.reporting.rows import (
    MARKERS,
    CommandRow,
    CommandState,
    CopyRow,
    CopyState,
    FileRow,
    FileState,
    InsertionLine,
    InsertionState,
    PromotedRow,
    PromotedState,
    ProviderBranch,
    SessionGroup,
    SymlinkRow,
    ValidatorLine,
    ValidatorState,
    marker_for,
)

__all__ = [
    'MARKERS',
    'CommandRow',
    'CommandState',
    'CopyRow',
    'CopyState',
    'FileRow',
    'FileState',
    'InsertionLine',
    'InsertionState',
    'PromotedRow',
    'PromotedState',
    'ProviderBranch',
    'SessionGroup',
    'SummaryNode',
    'SymlinkRow',
    'ValidatorLine',
    'ValidatorState',
    'details_link',
    'marker_for',
    'post_process_nodes',
    'print_completed_footer',
    'print_run_header',
    'print_summary_trees',
    'render_summary_tree',
    'session_label',
    'stat_suffix',
]
