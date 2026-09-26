"""Contract tests for summary-tree nodes and label helpers."""

from pathlib import Path

from pytest_mock import MockerFixture
from rich.text import Text

from repolish.reporting.nodes import (
    SummaryNode,
    details_link,
    stat_suffix,
)


def test_summary_node_defaults():
    node = SummaryNode(label=Text('row'))
    assert node.label.plain == 'row'
    assert node.children == []
    assert node.link is None


def test_stat_suffix_joins_parts_with_dim_dots():
    text = Text('group')
    stat_suffix(
        text,
        ['[green]2 written[/green]', '[yellow]1 skipped[/yellow]'],
    )
    assert text.plain == 'group  2 written · 1 skipped'
    # separators are dim; parts keep their markup styles
    spans = [(s.start, s.end, s.style) for s in text.spans]
    assert any(style == 'dim' and text.plain[s:e] == ' · ' for s, e, style in spans)


def test_details_link_appends_link_when_supported(
    mocker: MockerFixture,
    tmp_path: Path,
):
    mocker.patch('repolish.reporting.nodes.supports_hyperlinks', new=True)
    report_path = tmp_path / 'report.txt'
    text = Text('cmd')
    details_link(text, report_path)
    assert text.plain == 'cmd [details]'
    expected_link = f'link file://{report_path}'
    assert any(expected_link in str(s.style) for s in text.spans)


def test_details_link_noop_without_hyperlink_support(
    mocker: MockerFixture,
    tmp_path: Path,
):
    mocker.patch('repolish.reporting.nodes.supports_hyperlinks', new=False)
    text = Text('cmd')
    details_link(text, tmp_path / 'report.txt')
    assert text.plain == 'cmd'
