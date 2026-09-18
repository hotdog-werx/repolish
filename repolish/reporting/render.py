"""Render `SummaryNode` trees into rich output.

The only place that knows about rich `Tree` assembly and hyperlink styles
for summaries: producers hand over plain node data, this module prints.
"""

from collections.abc import Sequence
from pathlib import Path

from rich.text import Text
from rich.tree import Tree

from repolish.console import console, supports_hyperlinks
from repolish.postprocess.report import format_duration
from repolish.reporting.nodes import SummaryNode, details_link
from repolish.version import __version__


def _add_nodes(tree: Tree, nodes: Sequence[SummaryNode]) -> None:
    for node in nodes:
        label = node.label
        # Always stylize, but use empty style when there is no link to open
        # (avoids uncovered branch).
        link = f'link file://{node.link.absolute()}' if node.link is not None and supports_hyperlinks else ''
        label.stylize(link)
        branch = tree.add(label)
        _add_nodes(branch, node.children)


def render_summary_tree(title: str, nodes: Sequence[SummaryNode]) -> Tree:
    """Build a rich `Tree` titled *title* from *nodes*."""
    tree = Tree(f'[bold]{title}[/bold]')
    _add_nodes(tree, nodes)
    return tree


def print_summary_trees(
    sections: Sequence[tuple[str, Sequence[SummaryNode]]],
) -> None:
    """Print each titled section that has nodes, in order, separated by a blank line."""
    printed = False
    for title, nodes in sections:
        if not nodes:
            continue
        if printed:
            console.print()
        console.print(render_summary_tree(title, nodes))
        printed = True


def print_run_header(parts: Sequence[str]) -> None:
    """Print the one-line run header above the summary trees.

    The header names the run: the repolish version plus one dim part per
    detail the entry point adds (a fast lane names its lane and provider,
    a check run says ``check``). It carries the same weight as the
    completion footer, so the trees stay the visual center of the output.
    """
    text = Text(f'repolish {__version__}')
    for part in parts:
        text.append(f' · {part}', style='dim')
    console.print(text)


def print_completed_footer(total_ms: int, timings_path: Path) -> None:
    """Print the one-line run footer with a details link to the timings file."""
    text = Text(f'completed in {format_duration(total_ms)}')
    details_link(text, timings_path)
    console.print(text)
