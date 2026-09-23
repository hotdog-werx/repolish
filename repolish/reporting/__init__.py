"""Reporting: the drawing half of the summary.

Derivation lives in `repolish.summaries`: it turns a finished session
into typed rows. This package turns rows into output — markers, leaf
renderers, and the console printer. Terminal today; a future
`print_summary_html` consumes the same rows.

Public surface is just the print/render entry points plus the tree node;
markers, leaves, and their details live in submodules.
"""

from repolish.reporting.nodes import SummaryNode
from repolish.reporting.render import (
    print_completed_footer,
    print_run_header,
    print_summary_trees,
    render_summary_tree,
)

__all__ = [
    'SummaryNode',
    'print_completed_footer',
    'print_run_header',
    'print_summary_trees',
    'render_summary_tree',
]
