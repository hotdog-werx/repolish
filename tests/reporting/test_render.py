"""Rendering tests: SummaryNode trees become rich output via repolish.console."""

import io
from collections.abc import Sequence

from pytest_mock import MockerFixture
from rich.console import Console
from rich.text import Text

from repolish.reporting import (
    SummaryNode,
    print_summary_trees,
    render_summary_tree,
)


def _capture(
    mocker: MockerFixture,
    sections: Sequence[tuple[str, Sequence[SummaryNode]]],
) -> str:
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)
    print_summary_trees(sections)
    return out.getvalue()


def test_render_summary_tree_builds_titled_tree():
    tree = render_summary_tree(
        'apply summary',
        [
            SummaryNode(
                label=Text('alpha'),
                children=[SummaryNode(label=Text('beta'))],
            ),
        ],
    )
    assert tree.label == '[bold]apply summary[/bold]'
    assert len(tree.children) == 1
    out = io.StringIO()
    Console(file=out, force_terminal=False, no_color=True).print(tree)
    rendered = out.getvalue()
    assert 'alpha' in rendered
    assert 'beta' in rendered


def test_print_summary_trees_prints_only_non_empty_sections(
    mocker: MockerFixture,
):
    output = _capture(
        mocker,
        [
            ('post-process summary', []),
            ('apply summary', [SummaryNode(label=Text('row'))]),
        ],
    )
    assert 'post-process summary' not in output
    assert 'apply summary' in output
    assert 'row' in output


def test_print_summary_trees_separates_sections_with_blank_line(
    mocker: MockerFixture,
):
    output = _capture(
        mocker,
        [
            ('post-process summary', [SummaryNode(label=Text('cmd'))]),
            ('apply summary', [SummaryNode(label=Text('row'))]),
        ],
    )
    assert output.index('post-process summary') < output.index('apply summary')
    # a blank line between the two trees, none after the last
    assert 'cmd\n\napply summary' in output


def test_print_summary_trees_nothing_to_print(mocker: MockerFixture):
    assert _capture(mocker, [('a', []), ('b', [])]) == ''
