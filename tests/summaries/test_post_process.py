"""Derivation tests for the post-process summary: session runs in, rows out.

Every test hand-builds a `ResolvedSession` (no pipeline, no rendering) with
post-process runs and reports and asserts the group rows the derivation
produces: session labels, command rows, counts, subgroups, and the strict
failures.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import pytest

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
from repolish.summaries.post_process import (
    _command_row,
    post_process_rows,
    session_label,
)
from repolish.summaries.rows import CommandState, PostProcessGroup

if TYPE_CHECKING:
    from collections.abc import Sequence


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


def _session_with_run(
    tmp_path: Path,
    *outcomes: CommandOutcome,
    label: str = 'session',
) -> ResolvedSession:
    session = _make_session(tmp_path)
    session.post_process_runs.append(
        (label, PostProcessRun(cwd=tmp_path, outcomes=list(outcomes))),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.txt',
    )
    return session


def test_session_without_runs_derives_no_group(tmp_path: Path) -> None:
    assert post_process_rows([_make_session(tmp_path)]) == []


def test_command_rows_carry_raw_state_and_duration(tmp_path: Path) -> None:
    session = _session_with_run(
        tmp_path,
        _outcome('ruff format {render_dir}', 'ok', duration_ms=1200),
    )
    (group,) = post_process_rows([session])
    assert group.label == tmp_path.name  # the standalone directory name
    assert group.link == tmp_path / '.repolish' / '_' / 'post-process.txt'
    assert group.ok == 1
    (row,) = group.commands
    assert row.raw == 'ruff format {render_dir}'
    assert row.state is CommandState.OK
    assert row.duration_ms == 1200


def test_failed_and_not_run_states_and_counts(tmp_path: Path) -> None:
    session = _session_with_run(
        tmp_path,
        _outcome('dprint fmt {render_dir}', 'failed', returncode=1),
        _outcome('ruff check .', 'not_run'),
    )
    (group,) = post_process_rows([session])
    assert group.failed == 1
    assert group.not_run == 1
    assert [(row.state, row.returncode) for row in group.commands] == [
        (CommandState.FAILED, 1),
        (CommandState.NOT_RUN, None),
    ]


def test_command_row_error_field(tmp_path: Path) -> None:
    session = _session_with_run(
        tmp_path,
        _outcome('no-such-tool .', 'failed', error='[Errno 2] No such file'),
    )
    (group,) = post_process_rows([session])
    assert group.commands[0].error == '[Errno 2] No such file'


def test_command_row_falls_back_to_argv_when_raw_is_empty() -> None:
    row = _command_row(
        CommandOutcome(
            raw=(),
            argv=('make', 'fmt'),
            status='ok',
        ),
    )
    assert row.raw == 'make fmt'


def test_unknown_outcome_status_is_rejected() -> None:
    """An unmapped runner status fails loudly instead of rendering a marker."""
    with pytest.raises(ValueError, match='unknown post-process outcome status'):
        _command_row(
            CommandOutcome(
                raw=('make',),
                argv=('make',),
                status=cast('OutcomeStatus', 'exploded'),
            ),
        )


def test_runs_and_reports_must_pair_up(tmp_path: Path) -> None:
    """The strict zip fails loudly when a run lacks its report path."""
    session = _make_session(tmp_path)
    session.post_process_runs.append(
        ('session', PostProcessRun(cwd=tmp_path, outcomes=[])),
    )
    with pytest.raises(ValueError, match='zip'):
        post_process_rows([session])


def test_promoted_files_run_nests_as_labeled_subgroup(tmp_path: Path) -> None:
    session = _session_with_run(tmp_path, _outcome('ruff format .', 'ok'))
    session.post_process_runs.append(
        (
            'promoted files',
            PostProcessRun(
                cwd=tmp_path,
                outcomes=[_outcome('dprint fmt .', 'ok')],
            ),
        ),
    )
    session.post_process_reports.append(
        tmp_path / '.repolish' / '_' / 'post-process.promoted.txt',
    )
    (group,) = post_process_rows([session])
    assert group.ok == 2  # counts span the session and its subgroup
    (sub,) = group.subgroups
    assert sub.label == 'promoted files'
    assert sub.link == tmp_path / '.repolish' / '_' / 'post-process.promoted.txt'
    assert sub.ok == 1
    assert sub.commands[0].raw == 'dprint fmt .'


def test_session_label_member_name_beats_the_directory(
    tmp_path: Path,
) -> None:
    session = _make_session(
        tmp_path / 'member-dir',
        'member',
        providers=_member_bundle('pkg-alpha'),
    )
    assert session_label(session) == 'pkg-alpha'


def test_session_label_skips_root_and_unnamed_contexts(
    tmp_path: Path,
) -> None:
    session = _make_session(
        tmp_path / 'member-dir',
        'member',
        providers=_member_bundle('_root', '', 'pkg-beta'),
    )
    assert session_label(session) == 'pkg-beta'


def test_session_label_falls_back_to_the_directory(
    tmp_path: Path,
) -> None:
    """Member mode without usable contexts, and every other mode, use the config directory name."""
    bare = _make_session(tmp_path / 'member-dir', 'member')
    assert session_label(bare) == 'member-dir'
    standalone = _make_session(tmp_path / 'repo', 'standalone')
    assert session_label(standalone) == 'repo'


def test_groups_per_session_in_order(tmp_path: Path) -> None:
    sessions: Sequence[ResolvedSession] = [
        _session_with_run(tmp_path / name, _outcome('ruff format .', 'ok')) for name in ('alpha', 'beta')
    ]
    groups = post_process_rows(sessions)
    assert [group.label for group in groups] == ['alpha', 'beta']


def test_groups_are_post_process_row_data(tmp_path: Path) -> None:
    session = _session_with_run(tmp_path, _outcome('ruff format .', 'ok'))
    (group,) = post_process_rows([session])
    assert isinstance(group, PostProcessGroup)
    assert group.commands
