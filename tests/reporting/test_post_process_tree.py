"""Post-process summary tree producer tests, asserted on rendered output."""

import io
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

import pytest
from pytest_mock import MockerFixture
from rich.console import Console

from repolish.commands.apply.options import ResolvedSession
from repolish.config.models import RepolishConfig
from repolish.postprocess.models import (
    CommandOutcome,
    OutcomeStatus,
    PostProcessRun,
)
from repolish.providers import SessionBundle
from repolish.providers.models import GlobalContext
from repolish.providers.models.context import (
    BaseContext,
    ProviderInfo,
    RepolishContext,
)
from repolish.providers.models.workspace import (
    ProviderSession,
    WorkspaceContext,
)
from repolish.reporting import print_summary_trees
from repolish.reporting.leaves import render_post_process_summary
from repolish.summaries.post_process import _command_row, post_process_rows


def _make_session(
    tmp_path: Path,
    mode: Literal['root', 'member', 'standalone'] = 'standalone',
    *,
    providers: SessionBundle | None = None,
) -> ResolvedSession:
    config = RepolishConfig(
        config_dir=tmp_path,
        providers={},
        paused_files=[],
    )
    global_context = GlobalContext(workspace=WorkspaceContext(mode=mode))
    return ResolvedSession(
        config_path=tmp_path / 'repolish.yaml',
        config=config,
        global_context=global_context,
        providers=providers or SessionBundle(),
    )


def _member_bundle(*member_names: str) -> SessionBundle:
    """Bundle whose provider contexts carry the given member names, in order."""
    contexts = {}
    for provider_id, name in enumerate(member_names):
        contexts[f'provider-{provider_id}'] = BaseContext(
            repolish=RepolishContext(
                provider=ProviderInfo(
                    session=ProviderSession(member_name=name),
                ),
            ),
        )
    return SessionBundle(provider_contexts=contexts)


def _outcome(  # noqa: PLR0913 - its a test helper
    raw: str,
    status: Literal['ok', 'failed', 'not_run'],
    *,
    duration_ms: int = 0,
    returncode: int | None = None,
    output: str = '',
    error: str | None = None,
) -> CommandOutcome:
    return CommandOutcome(
        raw=tuple(raw.split()),
        argv=tuple(raw.split()),
        status=status,
        duration_ms=duration_ms,
        returncode=returncode,
        output=output,
        error=error,
    )


def _render(mocker: MockerFixture, sessions: Sequence[ResolvedSession]) -> str:
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.reporting.render.console', test_console)
    print_summary_trees(
        [
            (
                'post-process summary',
                render_post_process_summary(post_process_rows(sessions)),
            ),
        ],
    )
    return out.getvalue()


def test_no_groups_without_runs(mocker: MockerFixture, tmp_path: Path):
    assert post_process_rows([_make_session(tmp_path)]) == []
    assert _render(mocker, [_make_session(tmp_path)]) == ''


def test_command_rows_show_marker_raw_command_and_duration(
    mocker: MockerFixture,
    tmp_path: Path,
):
    session = _make_session(tmp_path)
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[
                    _outcome(
                        'ruff format {render_dir}',
                        'ok',
                        duration_ms=1200,
                    ),
                ],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    assert 'post-process summary' in output
    # group label is the standalone session directory
    assert tmp_path.name in output
    assert '✓ ruff format {render_dir}' in output
    assert 'ok (1.2s)' in output
    assert '1 ok' in output


def test_failed_and_not_run_rows(mocker: MockerFixture, tmp_path: Path):
    session = _make_session(tmp_path)
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[
                    _outcome('dprint fmt {render_dir}', 'failed', returncode=1),
                    _outcome('ruff check .', 'not_run'),
                ],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    assert '✗ dprint fmt {render_dir}' in output
    assert 'FAILED exit 1' in output
    assert 'not run (previous command failed)' in output
    assert '1 failed' in output
    assert '1 not run' in output


def test_missing_executable_row_shows_error(
    mocker: MockerFixture,
    tmp_path: Path,
):
    session = _make_session(tmp_path)
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[
                    _outcome(
                        'no-such-tool .',
                        'failed',
                        error='[Errno 2] No such file',
                    ),
                ],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    assert '✗ no-such-tool .' in output
    assert 'FAILED [Errno 2] No such file' in output


def test_root_session_group_labelled_root(
    mocker: MockerFixture,
    tmp_path: Path,
):
    session = _make_session(tmp_path, mode='root')
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[_outcome('ruff format .', 'ok')],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    assert 'root' in output


def test_promoted_files_run_nests_as_labeled_subgroup(
    mocker: MockerFixture,
    tmp_path: Path,
):
    session = _make_session(tmp_path, mode='root')
    session.post_process_runs.extend(
        [
            (
                'session',
                PostProcessRun(
                    cwd=tmp_path,
                    outcomes=[_outcome('ruff format .', 'ok')],
                ),
            ),
            (
                'promoted files',
                PostProcessRun(
                    cwd=tmp_path,
                    outcomes=[_outcome('dprint fmt .', 'ok')],
                ),
            ),
        ],
    )
    session.post_process_reports.extend(
        [
            tmp_path / '.repolish' / '_' / 'post-process.txt',
            tmp_path / '.repolish' / '_' / 'post-process.promoted.txt',
        ],
    )
    output = _render(mocker, [session])
    assert 'promoted files' in output
    assert '2 ok' in output
    assert 'dprint fmt .' in output


def test_member_session_without_contexts_falls_back_to_directory(
    mocker: MockerFixture,
    tmp_path: Path,
):
    session = _make_session(tmp_path, mode='member')
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[_outcome('ruff format .', 'ok')],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    assert tmp_path.name in output


def test_member_session_group_labelled_by_member_name(
    mocker: MockerFixture,
    tmp_path: Path,
):
    session = _make_session(
        tmp_path / 'member-dir',
        'member',
        providers=_member_bundle('pkg-alpha'),
    )
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[_outcome('ruff format .', 'ok')],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    # the member name from the provider contexts, not the config directory
    assert 'pkg-alpha' in output
    assert 'member-dir' not in output


def test_member_session_skips_root_and_unnamed_contexts(
    mocker: MockerFixture,
    tmp_path: Path,
):
    session = _make_session(
        tmp_path / 'member-dir',
        'member',
        providers=_member_bundle('_root', '', 'pkg-beta'),
    )
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[_outcome('ruff format .', 'ok')],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    assert 'pkg-beta' in output


def test_details_links_render_when_hyperlinks_supported(
    mocker: MockerFixture,
    tmp_path: Path,
):
    mocker.patch('repolish.reporting.nodes.supports_hyperlinks', new=True)
    session = _make_session(tmp_path)
    session.post_process_runs.append(
        (
            'session',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[
                    _outcome('ruff format .', 'ok'),
                    _outcome('dprint fmt .', 'ok'),
                ],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    output = _render(mocker, [session])
    # one details link per group (the commands share one report file), not
    # per command; the link target itself is a hyperlink style, asserted
    # in test_nodes.py
    assert output.count('[details]') == 1
    group_row = next(line for line in output.splitlines() if tmp_path.name in line)
    assert '[details]' in group_row
    command_row = next(line for line in output.splitlines() if 'ruff format' in line)
    assert '[details]' not in command_row


def test_groups_per_session_in_order(mocker: MockerFixture, tmp_path: Path):
    sessions = []
    for name in ('alpha', 'beta'):
        session = _make_session(tmp_path / name)
        session.post_process_runs.append(
            (
                'session',
                PostProcessRun(
                    cwd=tmp_path,
                    outcomes=[_outcome('ruff format .', 'ok')],
                ),
            ),
        )
        session.post_process_reports.append(
            tmp_path / name / '.repolish' / '_' / 'post-process.txt',
        )
        sessions.append(session)
    output = _render(mocker, sessions)
    assert output.index('alpha') < output.index('beta')


def test_unknown_outcome_status_is_rejected():
    """An unmapped runner status fails loudly instead of rendering a marker."""
    with pytest.raises(ValueError, match='unknown post-process outcome status'):
        _command_row(
            CommandOutcome(
                raw=('make',),
                argv=('make',),
                status=cast('OutcomeStatus', 'exploded'),
            ),
        )
