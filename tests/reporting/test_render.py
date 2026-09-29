"""Rendering tests: SummaryNode trees become rich output via repolish.console."""

import io
import json
from collections.abc import Sequence
from pathlib import Path

from pytest_mock import MockerFixture
from rich.console import Console
from rich.text import Text

from repolish.phases import PhaseTimer
from repolish.reporting import (
    SummaryNode,
    print_command_timings,
    print_completed_footer,
    print_run_header,
    print_summary_trees,
    render_summary_tree,
)
from repolish.version import __version__


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


def test_print_completed_footer_shows_duration_without_link_by_default(
    mocker: MockerFixture,
    tmp_path: Path,
):
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)
    print_completed_footer(4210, tmp_path / 'phase-timings.json')
    rendered = out.getvalue()
    assert 'completed in 4.2s' in rendered
    # no hyperlink support: the [details] suffix is absent
    assert '[details]' not in rendered
    # the footer opens with a blank line so it sits apart from the trees
    assert rendered.startswith('\ncompleted in')
    assert rendered.count('\n') == 2


def test_print_completed_footer_duration_only(mocker: MockerFixture):
    """Without a timings path the footer prints the duration, nothing else."""
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)
    print_completed_footer(4210)
    rendered = out.getvalue()
    assert 'completed in' in rendered
    assert '[details]' not in rendered


def test_print_command_timings_writes_command_named_file(
    mocker: MockerFixture,
    tmp_path: Path,
):
    """With a config dir the timings land in `<command>-phase-timings.json`."""
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)

    timer = PhaseTimer()
    timer.record('register', 12.0)
    print_command_timings('link', 5130.0, [('Standalone', timer)], tmp_path)

    payload = json.loads(
        (tmp_path / '.repolish' / '_' / 'link-phase-timings.json').read_text(
            encoding='utf-8',
        ),
    )
    assert payload['total_ms'] == 5130
    assert payload['sessions'][0]['name'] == 'Standalone'
    assert payload['sessions'][0]['phases'] == {'register': 12}
    assert 'completed in' in out.getvalue()


def test_print_command_timings_duration_only_without_config_dir(
    mocker: MockerFixture,
):
    """Without a config dir (lint, preview, scaffold) the footer has no file."""
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)

    print_command_timings('lint', 90.0)

    assert 'completed in' in out.getvalue()


def test_print_run_header_shows_version_and_dim_parts(
    mocker: MockerFixture,
):
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)
    print_run_header(['lane assets', 'provider demo', 'repolish.yaml'])
    rendered = out.getvalue()
    assert f'repolish {__version__}' in rendered
    assert 'lane assets' in rendered
    assert 'provider demo' in rendered
    assert 'repolish.yaml' in rendered
    assert ' · ' in rendered
    # the header closes with a blank line so the trees start clear of it
    assert rendered.count('\n') == 2


def test_print_run_header_without_parts_is_just_the_version(
    mocker: MockerFixture,
):
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)
    print_run_header([])
    rendered = out.getvalue()
    assert f'repolish {__version__}' in rendered
    assert ' · ' not in rendered
    assert rendered.count('\n') == 2
