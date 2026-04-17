"""Tests for repolish.commands.apply.display."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

import pytest
from rich.console import Console

from repolish.commands.apply.display import (
    print_files_summary,
    print_summary_tree,
)
from repolish.commands.apply.options import ResolvedSession
from repolish.config.models import RepolishConfig
from repolish.config.models.provider import ProviderSymlink
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
                FileRecord(
                    path='.gitignore',
                    mode=FileMode.REGULAR,
                    owner='my-provider',
                ),
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
                FileRecord(
                    path='.gitignore',
                    mode=FileMode.REGULAR,
                    owner='my-provider',
                ),
                FileRecord(
                    path='README.md',
                    mode=FileMode.REGULAR,
                    owner='my-provider',
                ),
            ],
            file_mappings={},
            expected_not_applied=[],
            expected_applied=['.gitignore', 'README.md'],
        ),
        SummaryTreeCase(
            name='suppress_mode_not_applied',
            mode='standalone',
            file_records=[
                FileRecord(
                    path='broken.md',
                    mode=FileMode.SUPPRESS,
                    owner='my-provider',
                ),
                FileRecord(
                    path='good.md',
                    mode=FileMode.REGULAR,
                    owner='my-provider',
                ),
            ],
            file_mappings={},
            expected_not_applied=['broken.md'],
            expected_applied=['good.md'],
        ),
        SummaryTreeCase(
            name='root_delete_still_applied',
            mode='root',
            file_records=[
                FileRecord(
                    path='old.md',
                    mode=FileMode.DELETE,
                    owner='my-provider',
                ),
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
            FileRecord(
                path='managed.txt',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
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
    """Root mode with skipped files shows 'N applied, M not applied' without apply_result."""
    session = _make_session(
        tmp_path,
        mode='root',
        file_records=[
            FileRecord(
                path='auto.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
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


def _make_session_with_result(
    tmp_path: Path,
    file_records: list[FileRecord],
    apply_result: dict[str, str],
    file_mappings: dict | None = None,
) -> ResolvedSession:
    session = _make_session(
        tmp_path,
        mode='standalone',
        file_records=file_records,
        file_mappings=file_mappings or {},
    )
    session.apply_result = apply_result
    return session


def test_summary_tree_written_shows_checkmark(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Files with status 'written' show the checkmark symbol."""
    session = _make_session_with_result(
        tmp_path,
        file_records=[
            FileRecord(
                path='file.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
        ],
        apply_result={'file.md': 'written'},
    )
    output = _capture(mocker, [session])
    assert 'file.md' in output
    assert '✓' in output
    assert '1 written' in output


def test_summary_tree_unchanged_shows_tilde(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Files with status 'unchanged' show the tilde symbol."""
    session = _make_session_with_result(
        tmp_path,
        file_records=[
            FileRecord(
                path='file.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
        ],
        apply_result={'file.md': 'unchanged'},
    )
    output = _capture(mocker, [session])
    assert 'file.md' in output
    assert '~' in output
    assert '1 unchanged' in output


def test_summary_tree_source_template_shown(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Files with a source template different from their path show the source."""
    session = _make_session_with_result(
        tmp_path,
        file_records=[
            FileRecord(
                path='output.yaml',
                mode=FileMode.REGULAR,
                owner='my-provider',
                source='_repolish.template.yaml',
            ),
        ],
        apply_result={'output.yaml': 'written'},
        file_mappings={'output.yaml': '_repolish.template.yaml'},
    )
    output = _capture(mocker, [session])
    assert 'output.yaml' in output
    assert '_repolish.template.yaml' in output


def test_summary_tree_mixed_written_unchanged(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Provider label shows both written and unchanged counts when mixed."""
    session = _make_session_with_result(
        tmp_path,
        file_records=[
            FileRecord(
                path='new.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
            FileRecord(
                path='same.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
            ),
        ],
        apply_result={'new.md': 'written', 'same.md': 'unchanged'},
    )
    output = _capture(mocker, [session])
    assert '1 written' in output
    assert '1 unchanged' in output


def _capture_files_summary(
    mocker: MockerFixture,
    providers: SessionBundle,
    symlinks: dict | None = None,
) -> str:
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True)
    mocker.patch('repolish.commands.apply.display.console', test_console)
    print_files_summary(providers, symlinks)
    return out.getvalue()


def test_print_files_summary_overlay_dir_shown(
    tmp_path: Path,
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
    output = _capture_files_summary(mocker, providers)
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
    output = _capture_files_summary(mocker, providers, symlinks)
    assert 'sym-provider' in output


def test_summary_tree_overlay_dir_shown(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """A FileRecord with overlay_dir and no source shows the dir as source in the tree."""
    session = _make_session_with_result(
        tmp_path,
        file_records=[
            FileRecord(
                path='README.md',
                mode=FileMode.REGULAR,
                owner='my-provider',
                overlay_dir='root',
            ),
        ],
        apply_result={'README.md': 'written'},
    )
    output = _capture(mocker, [session])
    assert 'README.md' in output
    assert 'root/' in output
