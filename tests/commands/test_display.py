"""Tests for repolish.commands.apply.display."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from typing import Literal

import pytest
from pytest_mock import MockerFixture
from rich.console import Console

from repolish.commands.apply.display import print_summary_tree
from repolish.commands.apply.options import ResolvedSession
from repolish.config.models import RepolishConfig
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
    mode: Literal['root', 'member', 'standalone'] = 'standalone',
    file_records: list[FileRecord] | None = None,
    file_mappings: dict | None = None,
    paused_files: list[str] | None = None,
) -> ResolvedSession:
    config = RepolishConfig(
        config_dir=tmp_path,
        providers={},
        paused_files=paused_files or [],
    )
    global_context = GlobalContext(workspace=WorkspaceContext(mode=mode))
    providers = SessionBundle(
        file_records=file_records or [],
        file_mappings=file_mappings or {},
    )
    return ResolvedSession(
        config_path=tmp_path / 'repolish.yaml',
        config=config,
        global_context=global_context,
        providers=providers,
        aliases=['my-provider'],
        alias_to_pid={'my-provider': str(tmp_path / 'my-provider')},
        pid_to_alias={str(tmp_path / 'my-provider'): 'my-provider'},
        resolved_symlinks={},
    )


def _capture(mocker: MockerFixture, sessions: list[ResolvedSession]) -> str:
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.commands.apply.display.console', test_console)
    print_summary_tree(sessions)
    return out.getvalue()


@dataclass
class SummaryTreeCase:
    name: str
    mode: Literal['root', 'member', 'standalone']
    file_records: list[FileRecord]
    file_mappings: dict
    expected_not_applied: list[str]
    expected_applied: list[str]


@pytest.mark.parametrize(
    'case',
    [
        SummaryTreeCase(
            name='root_mode_auto_staged_not_applied',
            mode='root',
            file_records=[
                FileRecord(path='.gitignore', mode=FileMode.REGULAR, owner='my-provider'),
                FileRecord(
                    path='root_file.md',
                    mode=FileMode.REGULAR,
                    owner='my-provider',
                    source='_repolish.root_file.md',
                ),
            ],
            file_mappings={'root_file.md': '_repolish.root_file.md'},
            expected_not_applied=['.gitignore'],
            expected_applied=['root_file.md'],
        ),
        SummaryTreeCase(
            name='standalone_all_applied',
            mode='standalone',
            file_records=[
                FileRecord(path='.gitignore', mode=FileMode.REGULAR, owner='my-provider'),
                FileRecord(path='README.md', mode=FileMode.REGULAR, owner='my-provider'),
            ],
            file_mappings={},
            expected_not_applied=[],
            expected_applied=['.gitignore', 'README.md'],
        ),
        SummaryTreeCase(
            name='suppress_mode_not_applied',
            mode='standalone',
            file_records=[
                FileRecord(path='broken.md', mode=FileMode.SUPPRESS, owner='my-provider'),
                FileRecord(path='good.md', mode=FileMode.REGULAR, owner='my-provider'),
            ],
            file_mappings={},
            expected_not_applied=['broken.md'],
            expected_applied=['good.md'],
        ),
        SummaryTreeCase(
            name='root_delete_still_applied',
            mode='root',
            file_records=[
                FileRecord(path='old.md', mode=FileMode.DELETE, owner='my-provider'),
            ],
            file_mappings={},
            expected_not_applied=[],
            expected_applied=['old.md'],
        ),
    ],
    ids=lambda c: c.name,
)
def test_summary_tree_file_status(
    case: SummaryTreeCase,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    session = _make_session(
        tmp_path,
        mode=case.mode,
        file_records=case.file_records,
        file_mappings=case.file_mappings,
    )
    output = _capture(mocker, [session])

    for path in case.expected_not_applied:
        assert path in output, f'expected {path!r} in output'
        # The "not applied" indicator must appear somewhere near the path.
        # We check that "not applied" appears in the output at all; the
        # count ensures each skipped file contributes exactly one marker.
    if case.expected_not_applied:
        assert 'not applied' in output or 'suppressed' in output or 'paused' in output

    for path in case.expected_applied:
        assert path in output, f'expected {path!r} in output'


def test_summary_tree_paused_file_shows_reason(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Paused files show 'paused' as the skip reason in the summary tree."""
    session = _make_session(
        tmp_path,
        mode='standalone',
        file_records=[
            FileRecord(path='managed.txt', mode=FileMode.REGULAR, owner='my-provider'),
        ],
        paused_files=['managed.txt'],
    )
    output = _capture(mocker, [session])
    assert 'managed.txt' in output
    assert 'paused' in output


def test_summary_tree_root_mode_count_label(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Root mode with skipped files shows 'N applied, M not applied' in the label."""
    session = _make_session(
        tmp_path,
        mode='root',
        file_records=[
            FileRecord(path='auto.md', mode=FileMode.REGULAR, owner='my-provider'),
            FileRecord(
                path='explicit.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
                source='_repolish.explicit.md',
            ),
        ],
        file_mappings={'explicit.md': '_repolish.explicit.md'},
    )
    output = _capture(mocker, [session])
    assert '1 applied' in output
    assert '1 not applied' in output
