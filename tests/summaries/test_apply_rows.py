"""Derivation tests for the apply summary: session state in, rows out.

Every test hand-builds a `ResolvedSession` (no provider pipeline, no CLI)
and asserts the row the contract derives: file states for each disposition,
copy states in both modes, strict status-string mapping, and the
validator/insertion-only shapes.
"""

from pathlib import Path
from typing import Literal

import pytest

from repolish.commands.apply.options import InsertionFileResult, ResolvedSession
from repolish.config.models import RepolishConfig
from repolish.config.models.provider import ProviderCopy
from repolish.config.paused import is_paused
from repolish.providers.models import (
    FileMode,
    FileRecord,
    GlobalContext,
    SessionBundle,
    ValidationResult,
    ValidationStatus,
    WorkspaceContext,
)
from repolish.providers.models.context import (
    BaseContext,
    ProviderInfo,
    RepolishContext,
)
from repolish.providers.models.files import (
    FileValidatorOptions,
    FileValidatorSpec,
)
from repolish.providers.models.workspace import ProviderSession
from repolish.summaries.apply_rows import (
    apply_summary_rows,
    copy_row,
    file_row,
    file_state_from_status,
    promoted_row,
    session_groups,
    skip_state,
)
from repolish.summaries.rows import (
    AppliedStats,
    CopyRow,
    CopyState,
    FileRow,
    FileState,
    InsertionState,
    PendingStats,
    PromotedState,
    ValidatorState,
)
from repolish.utils import path_slug


def _validator_fn(
    context: object,
    path: Path,
) -> ValidationResult:  # pragma: no cover - never called
    return ValidationResult()


def _make_session(  # noqa: PLR0913 - per-aspect session overrides for derivation tests
    tmp_path: Path,
    *,
    mode: Literal['root', 'member', 'standalone'] = 'standalone',
    file_records: list[FileRecord] | None = None,
    file_mappings: dict | None = None,
    file_validators: dict | None = None,
    validator_sources: dict | None = None,
    file_insertions: dict | None = None,
    insertion_sources: dict | None = None,
    disabled_file_mappings: dict | None = None,
    paused_files: list[str] | None = None,
    apply_result: dict[str, str] | None = None,
    validation_results: dict | None = None,
    provider_filter: list[str] | None = None,
    resolved_copies: dict | None = None,
    paused_copies: dict | None = None,
    aliases: list[str] | None = None,
    alias_to_pid: dict | None = None,
    pid_to_alias: dict | None = None,
    provider_contexts: dict | None = None,
) -> ResolvedSession:
    config = RepolishConfig(
        config_dir=tmp_path,
        providers={},
        paused_files=paused_files or [],
    )
    providers = SessionBundle(
        file_records=file_records or [],
        file_mappings=file_mappings or {},
        file_validators=file_validators or {},
        validator_sources=validator_sources or {},
        file_insertions=file_insertions or {},
        insertion_sources=insertion_sources or {},
        disabled_file_mappings=disabled_file_mappings or {},
        provider_contexts=provider_contexts or {},
    )
    session = ResolvedSession(
        config_path=tmp_path / 'repolish.yaml',
        config=config,
        global_context=GlobalContext(workspace=WorkspaceContext(mode=mode)),
        providers=providers,
        aliases=aliases or ['p'],
        alias_to_pid=alias_to_pid or {'p': 'pid'},
        pid_to_alias=pid_to_alias or {'pid': 'p'},
        provider_filter=provider_filter,
        resolved_copies=resolved_copies or {},
        paused_copies=paused_copies or {},
    )
    session.apply_result = apply_result or {}
    session.validation_results = validation_results or {}
    return session


def _record(
    path: str,
    *,
    mode: FileMode = FileMode.REGULAR,
    source: str | None = None,
) -> FileRecord:
    return FileRecord(path=path, mode=mode, owner='p', source=source)


# --- strict status-string mapping -------------------------------------------


@pytest.mark.parametrize(
    ('status', 'expected'),
    [
        ('written', FileState.WRITTEN),
        ('unchanged', FileState.UNCHANGED),
        ('deleted', FileState.DELETED),
        ('drift', FileState.DRIFT),
        (None, FileState.OK),
    ],
)
def test_file_state_from_status_maps_known_strings(
    status: str | None,
    expected: FileState,
) -> None:
    assert file_state_from_status(status) is expected


def test_file_state_from_status_rejects_unknown_string() -> None:
    with pytest.raises(ValueError, match='unknown apply-result status'):
        file_state_from_status('exploded')


# --- skip states: paused, suppressed, disabled, root mode --------------------


@pytest.mark.parametrize(
    ('entry', 'path'),
    [
        ('a.md', 'a.md'),  # exact path
        ('.github', '.github/workflows/ci.yml'),  # directory subtree
        ('configs/*.txt', 'configs/b.txt'),  # glob
    ],
)
def test_skip_state_paused_matches_exact_directory_and_glob(
    tmp_path: Path,
    entry: str,
    path: str,
) -> None:
    assert is_paused(path, frozenset({entry}))
    session = _make_session(tmp_path, paused_files=[entry])
    assert skip_state(_record(path), session) is FileState.PAUSED


def test_skip_state_suppressed_and_disabled(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    assert skip_state(_record('a.md', mode=FileMode.SUPPRESS), session) is FileState.SUPPRESSED
    disabled = _make_session(tmp_path, disabled_file_mappings={'a.md': 'p/x'})
    assert skip_state(_record('a.md', mode=FileMode.SUPPRESS), disabled) is FileState.DISABLED


def test_skip_state_root_mode_skips_unmapped_regular_files(
    tmp_path: Path,
) -> None:
    session = _make_session(tmp_path, mode='root')
    # regular file with no mapping/validator/insertion claim: skipped
    assert skip_state(_record('a.md'), session) is FileState.ROOT_SKIPPED
    # delete/keep/suppress modes still apply at the root
    assert skip_state(_record('old.md', mode=FileMode.DELETE), session) is None
    # files the provider claims via create_file_mappings still apply
    mapped = _make_session(
        tmp_path,
        mode='root',
        file_mappings={'root.md': '_p/root.md'},
    )
    assert skip_state(_record('root.md', source='_p/root.md'), mapped) is None


def test_skip_state_standalone_applies_everything(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    assert skip_state(_record('a.md'), session) is None


# --- file rows ---------------------------------------------------------------


def test_file_row_status_states_from_apply_result(tmp_path: Path) -> None:
    session = _make_session(
        tmp_path,
        apply_result={'a.md': 'written', 'b.md': 'drift'},
    )
    written = file_row(_record('a.md'), session)
    assert written.state is FileState.WRITTEN
    assert written.source == ''
    drift = file_row(_record('b.md'), session)
    assert drift.state is FileState.DRIFT


def test_file_row_carries_file_context_link(tmp_path: Path) -> None:
    session = _make_session(tmp_path, apply_result={'a.md': 'written'})
    row = file_row(_record('a.md', source='_p/a.md'), session)
    expected = tmp_path / '.repolish' / '_' / 'file-ctx' / f'file-context.{path_slug("a.md")}.json'
    assert row.link == expected


def test_file_row_paused_carries_only_its_state(tmp_path: Path) -> None:
    session = _make_session(tmp_path, paused_files=['a.md'])
    row = file_row(_record('a.md'), session)
    assert row.state is FileState.PAUSED
    assert row.source == ''
    assert row.link is None
    assert row.validators == ()


def test_file_row_mode_note_and_source(tmp_path: Path) -> None:
    session = _make_session(tmp_path, apply_result={'a.md': 'written'})
    create_only = file_row(
        _record('a.md', mode=FileMode.CREATE_ONLY, source='_p/a.md'),
        session,
    )
    assert create_only.mode_note == 'create_only'
    assert create_only.source == '_p/a.md'


def test_file_row_insertion_only_not_staged(tmp_path: Path) -> None:
    session = _make_session(
        tmp_path,
        file_records=[_record('proj.md')],
        file_insertions={'proj.md': {'header': _validator_fn}},
    )
    session.insertion_results = {
        'proj.md': InsertionFileResult(total_blocks=2, failed_blocks=0),
    }
    row = file_row(_record('proj.md'), session)
    assert row.state is FileState.INSERTION_ONLY
    assert row.owner_note == 'developer owned'
    assert row.insertion is not None
    assert row.insertion.state is InsertionState.OK
    assert row.insertion.succeeded == 2


def test_file_row_insertion_only_hedges_under_provider_filter(
    tmp_path: Path,
) -> None:
    session = _make_session(
        tmp_path,
        file_insertions={'proj.md': {'header': _validator_fn}},
        provider_filter=['p'],
    )
    row = file_row(_record('proj.md'), session)
    assert row.owner_note == 'possibly provider-owned'


def test_file_row_validator_only_not_staged(tmp_path: Path) -> None:
    session = _make_session(
        tmp_path,
        file_validators={'README.md': {'lint': _validator_fn}},
        validator_sources={'README.md': 'pid'},
    )
    row = file_row(_record('README.md'), session)
    assert row.state is FileState.VALIDATOR_ONLY
    assert row.owner_note == 'developer owned'
    assert [line.state for line in row.validators] == [ValidatorState.PASS]


def test_file_row_validator_lines_cover_every_outcome(tmp_path: Path) -> None:
    session = _make_session(
        tmp_path,
        apply_result={'README.md': 'written'},
        file_validators={
            'README.md': {
                'lint': _validator_fn,
                'fmt': _validator_fn,
                'audit': FileValidatorSpec(
                    fn=_validator_fn,
                    options=FileValidatorOptions(enabled=False),
                ),
            },
        },
        validator_sources={'README.md': 'pid'},
        validation_results={
            'README.md': {
                'lint': ValidationResult(
                    status=ValidationStatus.WARNING,
                    message='spacing',
                ),
                'fmt': ValidationResult(
                    status=ValidationStatus.ERROR,
                    message='bad config',
                ),
            },
        },
    )
    row = file_row(_record('README.md'), session)
    by_name = {line.name: line for line in row.validators}
    assert by_name['lint'].state is ValidatorState.WARNING
    assert by_name['lint'].message == 'spacing'
    assert by_name['fmt'].state is ValidatorState.ERROR
    assert by_name['audit'].state is ValidatorState.DISABLED


def test_file_row_names_the_other_provider_that_owns_the_path(
    tmp_path: Path,
) -> None:
    session = _make_session(
        tmp_path,
        file_records=[
            FileRecord(
                path='shared.md',
                mode=FileMode.REGULAR,
                owner='q',
                source='_q/shared.md',
            ),
        ],
        file_validators={'shared.md': {'lint': _validator_fn}},
        validator_sources={'shared.md': 'pid'},
        apply_result={'shared.md': 'written'},
    )
    row = file_row(_record('shared.md', source='_p/shared.md'), session)
    assert row.state is FileState.VALIDATOR_ONLY
    assert row.owner_note == 'owned by q'


# --- copy rows ----------------------------------------------------------------


def _copy() -> ProviderCopy:
    return ProviderCopy(source=Path('p/configs'), target=Path('configs'))


def test_copy_row_active(tmp_path: Path) -> None:
    row = copy_row(_copy(), frozenset(), frozenset())
    assert row.state is CopyState.ACTIVE


def test_copy_row_paused_via_held_back_paths(tmp_path: Path) -> None:
    """Apply mode: the copy pass reports the whole target as held back."""
    row = copy_row(_copy(), frozenset({'configs'}), frozenset())
    assert row.state is CopyState.PAUSED


def test_copy_row_paused_via_pause_matcher_without_held_back_paths(
    tmp_path: Path,
) -> None:
    """Check mode: the matcher alone reports the whole-target pause.

    This is the check/apply parity contract: a whole-directory pause shows
    even when no copy pass ran (the repro case for the missing warning).
    """
    row = copy_row(_copy(), frozenset(), frozenset({'configs'}))
    assert row.state is CopyState.PAUSED


def test_copy_row_partially_paused_via_child_path(tmp_path: Path) -> None:
    row = copy_row(_copy(), frozenset({'configs/b.txt'}), frozenset())
    assert row.state is CopyState.PARTIALLY_PAUSED


# --- promoted rows --------------------------------------------------------------


@pytest.mark.parametrize(
    ('status', 'expected'),
    [
        (None, PromotedState.WRITTEN),
        ('written', PromotedState.WRITTEN),
        ('unchanged', PromotedState.UNCHANGED),
        ('differs', PromotedState.DIFFERS),
        ('overridden_by_root', PromotedState.OVERRIDDEN_BY_ROOT),
        ('paused', PromotedState.PAUSED),
        ('suppressed', PromotedState.SUPPRESSED),
    ],
)
def test_promoted_row_maps_every_status(
    status: str | None,
    expected: PromotedState,
) -> None:
    row = promoted_row(_record('pkg.md'), {'pkg.md': status} if status else {})
    assert row.state is expected


def test_promoted_row_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match='unknown promoted-result status'):
        promoted_row(_record('pkg.md'), {'pkg.md': 'exploded'})


# --- session groups and stats -----------------------------------------------------


def test_session_groups_apply_stats(tmp_path: Path) -> None:
    session = _make_session(
        tmp_path,
        file_records=[_record('a.md'), _record('b.md')],
        apply_result={'a.md': 'written', 'b.md': 'unchanged'},
    )
    (group,) = session_groups(session)
    assert group.title == 'Standalone'
    (branch,) = group.branches
    assert branch.stats == AppliedStats(written=1, unchanged=1)


def test_session_groups_pending_stats_without_apply_result(
    tmp_path: Path,
) -> None:
    session = _make_session(
        tmp_path,
        file_records=[_record('a.md'), _record('b.md')],
        paused_files=['b.md'],
    )
    session.apply_result = {}
    (group,) = session_groups(session)
    (branch,) = group.branches
    assert branch.stats == PendingStats(applied=1, not_applied=1)


def test_session_groups_reports_copy_pause_in_check_mode(
    tmp_path: Path,
) -> None:
    """A check-mode session reports the same partially-paused copy as apply.

    The paused_copies field is populated by the pure held-back computation
    in check mode, so derivation from either mode yields the same row.
    """
    session = _make_session(
        tmp_path,
        resolved_copies={'p': [_copy()]},
        paused_copies={'p': ['configs/b.txt']},
    )
    (group,) = session_groups(session)
    (branch,) = group.branches
    (copy_node,) = [row for row in branch.rows if isinstance(row, CopyRow)]
    assert copy_node.state is CopyState.PARTIALLY_PAUSED


# --- staged-file annotations (ownership, overlays, provider insertions) ------------


def test_file_row_on_a_staged_file_names_the_other_owner(
    tmp_path: Path,
) -> None:
    """A file another provider also claims keeps its apply status and says so."""
    session = _make_session(
        tmp_path,
        file_records=[
            FileRecord(
                path='shared.md',
                mode=FileMode.REGULAR,
                owner='q',
                source='_q/shared.md',
            ),
            _record('shared.md', source='_p/shared.md'),
        ],
        apply_result={'shared.md': 'written'},
    )
    row = file_row(_record('shared.md', source='_p/shared.md'), session)
    assert row.state is FileState.INSERTION_ONLY
    assert row.owner_note == 'owned by q'


def test_file_row_source_falls_back_to_the_overlay_dir(tmp_path: Path) -> None:
    """A file staged from a mode overlay cites the overlay, not a template."""
    session = _make_session(tmp_path, apply_result={'a.md': 'written'})
    record = FileRecord(
        path='a.md',
        mode=FileMode.REGULAR,
        owner='p',
        overlay_dir='root',
    )
    row = file_row(record, session)
    assert row.source == 'root/'


def test_file_row_uses_provider_scoped_insertion_results(
    tmp_path: Path,
) -> None:
    """Insertions come from the owning provider's result, not the aggregate."""
    session = _make_session(tmp_path, apply_result={'a.md': 'written'})
    session.provider_insertion_results = {
        'p': {
            'a.md': InsertionFileResult(
                total_blocks=3,
                failed_blocks=1,
                disabled_blocks=1,
            ),
        },
    }
    row = file_row(_record('a.md'), session)
    assert row.insertion is not None
    assert row.insertion.succeeded == 1
    assert row.insertion.failed == 1
    assert row.insertion.disabled == 1


def test_file_row_hides_zero_block_provider_insertions(tmp_path: Path) -> None:
    """A provider result with no blocks suppresses the insertion line."""
    session = _make_session(tmp_path, apply_result={'a.md': 'written'})
    session.provider_insertion_results = {
        'p': {'a.md': InsertionFileResult(total_blocks=0, failed_blocks=0)},
    }
    row = file_row(_record('a.md'), session)
    assert row.insertion is None


# --- validator- and insertion-owned records ---------------------------------------


def test_session_groups_attach_validator_owned_files(tmp_path: Path) -> None:
    """A file only a validator claims appears beneath the declaring provider."""
    session = _make_session(
        tmp_path,
        apply_result={'README.md': 'written'},
        file_validators={'README.md': {'lint': _validator_fn}},
        validator_sources={'README.md': 'pid'},
    )
    (group,) = session_groups(session)
    (branch,) = group.branches
    rows = [row for row in branch.rows if isinstance(row, FileRow)]
    assert [row.path for row in rows] == ['README.md']
    assert rows[0].state is FileState.OK


def test_session_groups_attach_insertion_owned_files(tmp_path: Path) -> None:
    """A file insertions claim appears beneath each provider that ran them."""
    session = _make_session(
        tmp_path,
        file_insertions={'a.md': {'header': _validator_fn}},
        insertion_sources={'a.md': ['pid']},
    )
    session.provider_insertion_results = {
        'p': {'a.md': InsertionFileResult(total_blocks=1, failed_blocks=0)},
    }
    (group,) = session_groups(session)
    (branch,) = group.branches
    rows = [row for row in branch.rows if isinstance(row, FileRow)]
    assert [row.path for row in rows] == ['a.md']
    assert rows[0].state is FileState.INSERTION_ONLY


def test_session_groups_skip_insertion_attachment_without_results(
    tmp_path: Path,
) -> None:
    """A declared insertion source with no executed blocks adds no row."""
    session = _make_session(
        tmp_path,
        file_records=[_record('a.md')],
        file_insertions={'a.md': {'header': _validator_fn}},
        insertion_sources={'a.md': ['pid']},
    )
    (group,) = session_groups(session)
    (branch,) = group.branches
    rows = [row for row in branch.rows if isinstance(row, FileRow)]
    assert [row.path for row in rows] == ['a.md']


# --- root / member / standalone classification -------------------------------------


def _role_context(
    mode: Literal['root', 'member', 'standalone'],
    member_name: str = '',
) -> BaseContext:
    return BaseContext(
        repolish=RepolishContext(
            provider=ProviderInfo(
                session=ProviderSession(mode=mode, member_name=member_name),
            ),
        ),
    )


def test_session_groups_classify_root_member_standalone(
    tmp_path: Path,
) -> None:
    session = _make_session(
        tmp_path,
        mode='root',
        aliases=['r', 'm', 's'],
        alias_to_pid={'r': 'pid-r', 'm': 'pid-m', 's': 'pid-s'},
        pid_to_alias={'pid-r': 'r', 'pid-m': 'm', 'pid-s': 's'},
        provider_contexts={
            'pid-r': _role_context('root'),
            'pid-m': _role_context('member', 'pkg-a'),
        },
    )
    titles = [group.title for group in session_groups(session)]
    assert titles == ['Root', 'Member: pkg-a', 'Standalone']


def test_root_group_carries_promoted_rows(tmp_path: Path) -> None:
    session = _make_session(
        tmp_path,
        mode='root',
        aliases=['r'],
        alias_to_pid={'r': 'pid-r'},
        pid_to_alias={'pid-r': 'r'},
        provider_contexts={'pid-r': _role_context('root')},
    )
    session.promoted_records = [
        FileRecord(
            path='pkg.md',
            mode=FileMode.REGULAR,
            owner='r',
            promoted_from='pkg-a',
        ),
    ]
    session.promoted_apply_result = {'pkg.md': 'written'}
    (root_group,) = session_groups(session)
    assert root_group.title == 'Root'
    (promoted,) = root_group.promoted
    assert promoted.path == 'pkg.md'
    assert promoted.promoted_from == 'pkg-a'


def test_apply_summary_rows_merges_sessions_in_order(tmp_path: Path) -> None:
    """Every session's groups flatten into one ordered row list."""
    first = _make_session(tmp_path / 'a')
    second = _make_session(tmp_path / 'b')
    groups = apply_summary_rows([first, second])
    assert [group.title for group in groups] == ['Standalone', 'Standalone']
