"""Tests for repolish.commands.apply.display.

The trees this module prints are owned by the library suites: `repolish.summaries`
derives the rows and `repolish.reporting` renders them, and both packages reach
100% from `tests/summaries` and `tests/reporting` alone. What is asserted here
is the command surface only: the pre-apply provider tables, the phase-timings
footer, and the composition that prints the sections in order.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

from rich.console import Console

from repolish.commands.apply.display import (
    print_files_summary,
    print_run_footer,
    print_run_summary,
)
from repolish.commands.apply.options import ResolvedSession
from repolish.config.models import RepolishConfig
from repolish.config.models.provider import ProviderSymlink
from repolish.postprocess.models import CommandOutcome, PostProcessRun
from repolish.providers.models import (
    FileMode,
    FileRecord,
    GlobalContext,
    SessionBundle,
    WorkspaceContext,
)


def _make_session(
    tmp_path: Path,
    *,
    file_records: list[FileRecord] | None = None,
) -> ResolvedSession:
    config = RepolishConfig(config_dir=tmp_path, providers={})
    global_context = GlobalContext(
        workspace=WorkspaceContext(mode='standalone'),
    )
    providers = SessionBundle(file_records=file_records or [], file_mappings={})
    return ResolvedSession(
        config_path=tmp_path / 'repolish.yaml',
        config=config,
        global_context=global_context,
        providers=providers,
        aliases=['my-provider'],
        alias_to_pid={'my-provider': str(tmp_path / 'my-provider')},
        pid_to_alias={str(tmp_path / 'my-provider'): 'my-provider'},
        resolved_symlinks={},
        resolved_copies={},
        paused_copies={},
    )


def _capture(mocker: MockerFixture, sessions: list[ResolvedSession]) -> str:
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)
    print_run_summary(sessions)
    return out.getvalue()


def test_print_files_summary_overlay_dir_shown(
    mocker: MockerFixture,
) -> None:
    """Records with overlay_dir and no source show the overlay dir as source column."""
    providers = SessionBundle(
        file_records=[
            FileRecord(
                path='README.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
                overlay_dir='root',
            ),
        ],
        file_mappings={},
    )
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.commands.apply.display.console', test_console)
    print_files_summary(providers)
    output = out.getvalue()
    assert 'README.md' in output
    assert 'root/' in output


def test_print_files_summary_symlinks_only_owner(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """An alias present only in the symlinks dict (no file records) still gets a table."""
    providers = SessionBundle(file_records=[], file_mappings={})
    symlinks = {
        'sym-provider': [
            ProviderSymlink(
                source=tmp_path / 'configs/.editorconfig',
                target=tmp_path / '.editorconfig',
            ),
        ],
    }
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.commands.apply.display.console', test_console)
    print_files_summary(providers, symlinks)
    assert 'sym-provider' in out.getvalue()


def test_print_run_summary_prints_post_process_before_apply(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Both sections print when the session ran post-process commands, in that order."""
    session = _make_session(
        tmp_path,
        file_records=[
            FileRecord(
                path='README.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
        ],
    )
    session.post_process_runs = [
        (
            tmp_path.name,
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[
                    CommandOutcome(raw=('make', 'fmt'), argv=('make', 'fmt')),
                ],
            ),
        ),
    ]
    session.post_process_reports = [tmp_path / 'report.txt']

    output = _capture(mocker, [session])
    assert 'post-process summary' in output
    assert 'apply summary' in output
    assert output.index('post-process summary') < output.index('apply summary')


def test_print_run_summary_skips_absent_post_process(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """A session that ran no post-process commands contributes only the apply tree."""
    session = _make_session(
        tmp_path,
        file_records=[
            FileRecord(
                path='README.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
        ],
    )
    output = _capture(mocker, [session])
    assert 'apply summary' in output
    assert 'post-process summary' not in output


def test_print_run_footer_writes_timings_json_and_footer_line(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """The footer writes phase-timings.json and prints the completion line."""
    session = _make_session(tmp_path)
    session.phase_timer.record('render', 183.0)

    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)

    print_run_footer([session], 4210.0, tmp_path)

    timings_path = tmp_path / '.repolish' / '_' / 'phase-timings.json'
    payload = json.loads(timings_path.read_text(encoding='utf-8'))
    assert payload['total_ms'] == 4210
    # the session name matches the post-process tree's group label
    assert payload['sessions'][0]['name'] == tmp_path.name
    assert payload['sessions'][0]['phases'] == {'render': 183}

    # the footer itself is repolish.reporting's to render; the command's job
    # is calling it after the timings are written, so any footer line will do.
    assert out.getvalue()
