"""Summary-tree contract: node producers build `SummaryNode` data, render prints."""

from repolish.reporting.nodes import (
    Status,
    SummaryNode,
    details_link,
    stat_suffix,
    status_prefix,
)
from repolish.reporting.post_process import post_process_nodes, session_label
from repolish.reporting.render import (
    print_completed_footer,
    print_summary_trees,
    render_summary_tree,
)

__all__ = [
    'Status',
    'SummaryNode',
    'details_link',
    'post_process_nodes',
    'print_completed_footer',
    'print_summary_trees',
    'render_summary_tree',
    'session_label',
    'stat_suffix',
    'status_prefix',
]
