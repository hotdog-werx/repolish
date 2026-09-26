"""Render `SummaryNode` trees into rich output.

The only place that knows about rich `Tree` assembly and hyperlink styles
for summaries: producers hand over plain node data, this module prints.
"""

from collections.abc import Sequence
from pathlib import Path

from rich.text import Text
from rich.tree import Tree

from repolish.console import console, supports_hyperlinks
from repolish.phases import PhaseTimer, write_phase_timings
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
    console.print(text, end='\n\n')


def print_completed_footer(
    total_ms: int,
    timings_path: Path | None = None,
) -> None:
    """Print the one-line run footer, linking to the timings file when there is one."""
    text = Text('\ncompleted in ')
    text.append(f'{format_duration(total_ms)}', style='dim')
    if timings_path is not None:
        details_link(text, timings_path)
    console.print(text)


def print_command_timings(
    command: str,
    total_ms: float,
    sessions: Sequence[tuple[str, PhaseTimer]] = (),
    config_dir: Path | None = None,
) -> None:
    """Write a command's phase-timings JSON and print the `completed in ...` footer.

    The single place every CLI command reports timing. With a *config_dir*
    the durations land in ``<config_dir>/.repolish/_/<command>-phase-timings.json``
    (one file per command, so runs never overwrite each other's timings)
    and the footer links to it. Commands that run outside a project
    (lint, preview, scaffold) pass no *config_dir* and get a duration-only
    footer — there is no project dir to host the file.
    """
    if config_dir is None:
        print_completed_footer(int(total_ms))
        return
    timings_path = write_phase_timings(
        config_dir / '.repolish' / '_' / f'{command}-phase-timings.json',
        total_ms,
        sessions,
    )
    print_completed_footer(int(total_ms), timings_path)
