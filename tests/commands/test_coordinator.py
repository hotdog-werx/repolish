"""Tests for coordinator promotion helpers and monorepo orchestration paths."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

from repolish.commands.apply.coordinator import (
    PromotedWriteContext,
    PromotionWinner,
    _apply_promotion_pass,
    _apply_winners,
    _post_process_promoted_files,
    _promoted_differs,
    _run_apply_phase,
    _run_root_pass,
    _sync_post_processed_promoted_files,
    coordinate_sessions,
)
from repolish.commands.apply.options import ApplyOptions, ResolvedSession
from repolish.commands.apply.utils import CoordinateOptions
from repolish.config.models import RepolishConfig
from repolish.providers import SessionBundle
from repolish.providers.models import GlobalContext, TemplateMapping
from repolish.providers.models.files import FileMode, FileRecord
from repolish.providers.models.workspace import MemberInfo, WorkspaceContext

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_session(config_dir: Path) -> ResolvedSession:
    """Return a minimal ResolvedSession rooted at *config_dir*."""
    config = RepolishConfig(
        config_dir=config_dir,
        providers={},
        paused_files=[],
    )
    gc = GlobalContext(workspace=WorkspaceContext(mode='member'))
    return ResolvedSession(
        config_path=config_dir / 'repolish.yaml',
        config=config,
        global_context=gc,
        providers=SessionBundle(),
    )


def _member(path: str, name: str) -> MemberInfo:
    return MemberInfo(path=Path(path), name=name, provider_aliases=frozenset())


def _write_render_file(
    render_dir: Path,
    name: str,
    content: str = 'body',
) -> Path:
    render_dir.mkdir(parents=True, exist_ok=True)
    out = render_dir / name
    out.write_text(content)
    return out


def _render_dir(root: Path, member: str) -> Path:
    return root / member / '.repolish' / '_' / 'render' / 'repolish'


# ---------------------------------------------------------------------------
# Promotion pass: prefixed source file (line 68) + check-only stale (303-308)
# ---------------------------------------------------------------------------


def test_apply_promotion_pass_uses_prefixed_source_when_exact_missing(
    tmp_path: Path,
) -> None:
    """_apply_promotion_pass resolves source via _repolish.-prefixed path when exact is absent.

    Covers:
    - _resolve_source_file line 68 (return prefixed)
    - _iter_pending_promotions line 126 (source_file = _resolve_source_file(...))
    - _apply_promoted_file lines 205-211 (logger.info 'promoted_file_differs')
    - _apply_promotion_pass lines 303-308 (return 2 when stale)
    """
    rdir = _render_dir(tmp_path, 'pkg')
    _write_render_file(rdir, '_repolish.tmpl.md', 'prefixed content')

    session = _make_session(tmp_path / 'pkg')
    session.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(source_template='tmpl.md'),
    }
    m = _member('pkg', 'pkg')
    opts = ApplyOptions(config_path=tmp_path / 'pkg' / 'repolish.yaml')

    root_session = _make_session(tmp_path)
    # out.md does not exist at root → 'differs' → returns 2
    rc = _apply_promotion_pass(
        [(m, session, opts)],
        root_session,
        check_only=True,
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# Promotion pass: hard conflict (line 290)
# Covers _conflict_winner 'error' strategy (lines 78-88)
# Covers _collect_promotion_winners conflict branch (lines 157-160)
# ---------------------------------------------------------------------------


def test_apply_promotion_pass_hard_conflict_returns_1(tmp_path: Path) -> None:
    """_apply_promotion_pass returns 1 when two members conflict with strategy='error'.

    Covers:
    - _conflict_winner lines 78-88 (strategy='error', logger.error + return None)
    - _collect_promotion_winners lines 157-160 (conflict branch + return None)
    - _apply_promotion_pass line 290 (return 1)
    """
    rdir_a = _render_dir(tmp_path, 'a')
    rdir_b = _render_dir(tmp_path, 'b')
    _write_render_file(rdir_a, 'tmpl.md', 'AAA')
    _write_render_file(rdir_b, 'tmpl.md', 'BBB')

    session_a = _make_session(tmp_path / 'a')
    session_a.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(
            source_template='tmpl.md',
            promote_conflict='error',
        ),
    }
    session_b = _make_session(tmp_path / 'b')
    session_b.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(
            source_template='tmpl.md',
            promote_conflict='error',
        ),
    }

    ma = _member('a', 'a')
    mb = _member('b', 'b')
    opts_a = ApplyOptions(config_path=tmp_path / 'a' / 'repolish.yaml')
    opts_b = ApplyOptions(config_path=tmp_path / 'b' / 'repolish.yaml')

    root_session = _make_session(tmp_path)
    rc = _apply_promotion_pass(
        [(ma, session_a, opts_a), (mb, session_b, opts_b)],
        root_session,
        check_only=True,
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# Promotion pass: last_wins conflict strategy (line 89)
# + write mode for promoted file (line 221)
# ---------------------------------------------------------------------------


def test_apply_promotion_pass_last_wins_writes_file(tmp_path: Path) -> None:
    """last_wins strategy lets second member override; write mode copies the file.

    Covers:
    - _conflict_winner line 89 (return challenger for 'last_wins')
    - _apply_promoted_file line 221 (filecmp block in write mode)
    """
    rdir_a = _render_dir(tmp_path, 'a')
    rdir_b = _render_dir(tmp_path, 'b')
    _write_render_file(rdir_a, 'tmpl.md', 'content-a')
    _write_render_file(rdir_b, 'tmpl.md', 'content-b')

    session_a = _make_session(tmp_path / 'a')
    session_a.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(
            source_template='tmpl.md',
            promote_conflict='last_wins',
        ),
    }
    session_b = _make_session(tmp_path / 'b')
    session_b.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(
            source_template='tmpl.md',
            promote_conflict='last_wins',
        ),
    }

    ma = _member('a', 'a')
    mb = _member('b', 'b')
    opts_a = ApplyOptions(config_path=tmp_path / 'a' / 'repolish.yaml')
    opts_b = ApplyOptions(config_path=tmp_path / 'b' / 'repolish.yaml')

    root_session = _make_session(tmp_path)
    # check_only=False → write mode
    rc = _apply_promotion_pass(
        [(ma, session_a, opts_a), (mb, session_b, opts_b)],
        root_session,
        check_only=False,
    )
    assert rc == 0
    assert (tmp_path / 'out.md').read_text() == 'content-b'


# ---------------------------------------------------------------------------
# Promotion pass: identical strategy with different content (lines 95-105)
# ---------------------------------------------------------------------------


def test_apply_promotion_pass_identical_conflict_different_content_returns_1(
    tmp_path: Path,
) -> None:
    """Identical strategy returns None (→ rc=1) when files differ.

    Covers:
    - _conflict_winner lines 95-105 (logger.error 'promote_conflict_not_identical' + return None)
    """
    rdir_a = _render_dir(tmp_path, 'a')
    rdir_b = _render_dir(tmp_path, 'b')
    _write_render_file(rdir_a, 'tmpl.md', 'AAAA')
    _write_render_file(rdir_b, 'tmpl.md', 'BBBB')

    session_a = _make_session(tmp_path / 'a')
    session_a.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(
            source_template='tmpl.md',
        ),  # default='identical'
    }
    session_b = _make_session(tmp_path / 'b')
    session_b.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(source_template='tmpl.md'),
    }

    ma = _member('a', 'a')
    mb = _member('b', 'b')
    opts_a = ApplyOptions(config_path=tmp_path / 'a' / 'repolish.yaml')
    opts_b = ApplyOptions(config_path=tmp_path / 'b' / 'repolish.yaml')

    root_session = _make_session(tmp_path)
    rc = _apply_promotion_pass(
        [(ma, session_a, opts_a), (mb, session_b, opts_b)],
        root_session,
        check_only=True,
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# _apply_winners: root-owned dest (lines 261-263, 170-182)
# ---------------------------------------------------------------------------


def test_apply_winners_root_owned_dest_records_override(tmp_path: Path) -> None:
    """When dest is root-owned, _apply_winners annotates it as 'overridden_by_root'.

    Covers:
    - _apply_winners lines 261-263 (promoted_records.append + continue)
    - _record_root_override lines 170-182 (loop mutation + return FileRecord)
    """
    src = tmp_path / 'src.md'
    src.write_text('hello')
    winner = PromotionWinner(
        dest='README.md',
        source_file=src,
        member_name='member-a',
        mapping=TemplateMapping(source_template='src.md'),
    )
    root_session = _make_session(tmp_path)
    root_session.providers.file_mappings = {'README.md': 'tmpl.md'}
    root_session.providers.file_records = [
        FileRecord(path='README.md', mode=FileMode.REGULAR, owner='root-prov'),
    ]

    records, result = _apply_winners(
        {'README.md': winner},
        root_session,
        check_only=True,
    )

    assert result['README.md'] == 'overridden_by_root'
    assert any(r.overridden_by == 'root' for r in records)
    assert root_session.providers.file_records[0].promoted_from == 'member-a'


# ---------------------------------------------------------------------------
# _run_root_pass: hard-conflict path (line 433)
# ---------------------------------------------------------------------------


def test_run_root_pass_returns_rc_on_promotion_conflict(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """_run_root_pass returns 1 immediately when _apply_promotion_pass returns 1.

    Covers line 433 (return rc when rc not in (0, 2)).
    """
    mocker.patch(
        'repolish.commands.apply.coordinator._apply_promotion_pass',
        return_value=1,
    )
    root_session = _make_session(tmp_path)
    opts = CoordinateOptions(check_only=False)
    rc = _run_root_pass([], root_session, tmp_path, [], opts)
    assert rc == 1


# ---------------------------------------------------------------------------
# _run_root_pass: apply_session failure path (line 443)
# ---------------------------------------------------------------------------


def test_run_root_pass_propagates_apply_session_failure(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """_run_root_pass propagates non-zero rc from apply_session.

    Covers line 443 (return rc when apply_session fails).
    """
    mocker.patch(
        'repolish.commands.apply.coordinator._apply_promotion_pass',
        return_value=0,
    )
    mocker.patch(
        'repolish.commands.apply.coordinator.apply_session',
        return_value=1,
    )
    root_session = _make_session(tmp_path)
    opts = CoordinateOptions(check_only=False)
    rc = _run_root_pass([], root_session, tmp_path, [], opts)
    assert rc == 1


# ---------------------------------------------------------------------------
# _run_apply_phase: root-pass failure path (line 471)
# ---------------------------------------------------------------------------


def test_run_apply_phase_returns_rc_when_root_pass_fails(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """_run_apply_phase returns (rc, []) when _run_root_pass returns non-(0|2).

    Covers line 471 (return rc, completed when _run_root_pass fails).
    """
    mocker.patch(
        'repolish.commands.apply.coordinator._apply_member_sessions',
        return_value=(0, []),
    )
    mocker.patch(
        'repolish.commands.apply.coordinator._run_root_pass',
        return_value=1,
    )
    root_session = _make_session(tmp_path)
    opts = CoordinateOptions(check_only=False)
    rc, completed = _run_apply_phase([], root_session, tmp_path, opts)
    assert rc == 1
    assert completed == []


# ---------------------------------------------------------------------------
# Promotion pass: identical strategy, same content (line 106)
# ---------------------------------------------------------------------------


def test_apply_promotion_pass_identical_same_content_keeps_first_winner(
    tmp_path: Path,
) -> None:
    """Identical strategy keeps the first winner when both members render same content.

    Covers _conflict_winner line 106 (return prev for identical files).
    """
    content = 'shared content\n'
    rdir_a = _render_dir(tmp_path, 'a')
    rdir_b = _render_dir(tmp_path, 'b')
    _write_render_file(rdir_a, 'tmpl.md', content)
    _write_render_file(rdir_b, 'tmpl.md', content)

    session_a = _make_session(tmp_path / 'a')
    session_a.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(
            source_template='tmpl.md',
        ),  # default='identical'
    }
    session_b = _make_session(tmp_path / 'b')
    session_b.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(source_template='tmpl.md'),
    }

    ma = _member('a', 'a')
    mb = _member('b', 'b')
    opts_a = ApplyOptions(config_path=tmp_path / 'a' / 'repolish.yaml')
    opts_b = ApplyOptions(config_path=tmp_path / 'b' / 'repolish.yaml')

    root_session = _make_session(tmp_path)
    # check_only=True, out.md not on disk → 'differs' → rc=2, but no conflict
    rc = _apply_promotion_pass(
        [(ma, session_a, opts_a), (mb, session_b, opts_b)],
        root_session,
        check_only=True,
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# Promotion pass: empty source_template skips entry (line 126)
# ---------------------------------------------------------------------------


def test_apply_promotion_pass_skips_mapping_with_no_source_template(
    tmp_path: Path,
) -> None:
    """Entries with source_template=None are skipped in _iter_pending_promotions.

    Covers _iter_pending_promotions line 126 (continue when source_template is falsy).
    """
    session = _make_session(tmp_path / 'pkg')
    session.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(source_template=None),
    }
    m = _member('pkg', 'pkg')
    opts = ApplyOptions(config_path=tmp_path / 'pkg' / 'repolish.yaml')

    root_session = _make_session(tmp_path)
    # No source_template → entry skipped → no winners → rc=0
    rc = _apply_promotion_pass(
        [(m, session, opts)],
        root_session,
        check_only=True,
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# Promotion pass: write mode with already-matching dest (line 221)
# ---------------------------------------------------------------------------


def test_apply_promotion_pass_write_mode_unchanged_when_dest_matches(
    tmp_path: Path,
) -> None:
    """Write mode reports 'unchanged' when dest already exists with same content.

    Covers _apply_promoted_file line 221 (result='unchanged' in write branch).
    """
    content = 'same content\n'
    rdir = _render_dir(tmp_path, 'pkg')
    _write_render_file(rdir, 'tmpl.md', content)

    session = _make_session(tmp_path / 'pkg')
    session.providers.promoted_file_mappings = {
        'out.md': TemplateMapping(source_template='tmpl.md'),
    }
    m = _member('pkg', 'pkg')
    opts = ApplyOptions(config_path=tmp_path / 'pkg' / 'repolish.yaml')

    # Write dest with the same content → check_only=False should see 'unchanged'
    (tmp_path / 'out.md').write_text(content)

    root_session = _make_session(tmp_path)
    rc = _apply_promotion_pass(
        [(m, session, opts)],
        root_session,
        check_only=False,
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# coordinate_sessions — monorepo happy path (line 535)
# ---------------------------------------------------------------------------


def test_coordinate_sessions_monorepo_returns_rc_and_prints_summary(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """coordinate_sessions runs the full monorepo path and returns rc.

    Patches at the imported-function level so real coordinator helpers run
    and reach line 535 ('return rc' at end of coordinate_sessions).
    """
    config_path = tmp_path / 'repolish.yaml'
    config_path.write_text('providers: {}\n')

    mono_ctx = WorkspaceContext(mode='root', members=[])

    # Return a raw config whose .workspace is falsy so _detect_workspace
    # delegates to detect_workspace() (which we mock below).
    raw_cfg_mock = mocker.MagicMock()
    raw_cfg_mock.workspace = None
    mocker.patch(
        'repolish.commands.apply.coordinator.load_config_file',
        return_value=raw_cfg_mock,
    )
    mocker.patch(
        'repolish.commands.apply.coordinator.detect_workspace',
        return_value=mono_ctx,
    )
    # Intercept resolve_session and apply_session so no real provider loading occurs.
    mocker.patch(
        'repolish.commands.apply.coordinator.resolve_session',
        return_value=_make_session(tmp_path),
    )
    mocker.patch(
        'repolish.commands.apply.coordinator.apply_session',
        return_value=0,
    )
    mock_print = mocker.patch(
        'repolish.commands.apply.coordinator.print_summary_tree',
    )

    rc = coordinate_sessions(config_path, CoordinateOptions(check_only=False))

    assert rc == 0
    assert mock_print.called


def test_apply_winners_skips_paused_promoted_destination(tmp_path: Path) -> None:
    """Promoted destinations listed in paused_files must not be written."""
    src = tmp_path / 'src.md'
    src.write_text('new-content')
    dest = tmp_path / 'out.md'
    dest.write_text('keep-existing')

    winner = PromotionWinner(
        dest='out.md',
        source_file=src,
        member_name='member-a',
        mapping=TemplateMapping(source_template='src.md'),
    )

    root_session = _make_session(tmp_path)
    root_session.providers.paused_files = frozenset({'out.md'})

    records, result = _apply_winners(
        {'out.md': winner},
        root_session,
        check_only=False,
    )

    assert result == {'out.md': 'paused'}
    assert records[0].path == 'out.md'
    assert dest.read_text() == 'keep-existing'


def test_apply_winners_skips_suppressed_promoted_source(tmp_path: Path) -> None:
    """Promoted sources suppressed by template overrides must not be written."""
    src = tmp_path / 'source.txt'
    src.write_text('new-content')
    dest = tmp_path / 'dest.txt'
    dest.write_text('keep-existing')

    winner = PromotionWinner(
        dest='dest.txt',
        source_file=src,
        member_name='member-a',
        mapping=TemplateMapping(source_template='source.txt'),
    )

    root_session = _make_session(tmp_path)
    root_session.providers.suppressed_sources = {'source.txt'}

    records, result = _apply_winners(
        {'dest.txt': winner},
        root_session,
        check_only=False,
    )

    assert result == {'dest.txt': 'suppressed'}
    assert records[0].path == 'dest.txt'
    assert dest.read_text() == 'keep-existing'


def test_apply_winners_preserves_regex_region_for_promoted_text(tmp_path: Path) -> None:
    """Promoted text files should preserve regex-managed content from destination."""
    src = tmp_path / 'source.txt'
    src.write_text(
        '## repolish-regex[member]: member:\\s*(.+)\nmember: default-member\n',
    )
    dest = tmp_path / 'dest.txt'
    dest.write_text('member: pkg-alpha\n')

    winner = PromotionWinner(
        dest='dest.txt',
        source_file=src,
        member_name='member-a',
        mapping=TemplateMapping(source_template='source.txt'),
    )

    root_session = _make_session(tmp_path)

    records, result = _apply_winners(
        {'dest.txt': winner},
        root_session,
        check_only=False,
    )

    assert records[0].path == 'dest.txt'
    assert result == {'dest.txt': 'unchanged'}
    assert dest.read_text() == 'member: pkg-alpha\n'


def test_apply_winners_binary_source_falls_back_to_copy(tmp_path: Path) -> None:
    """Binary promoted source should bypass text hydration and copy bytes unchanged."""
    src = tmp_path / 'source.bin'
    src.write_bytes(b'\xff\xfe\x00binary')

    winner = PromotionWinner(
        dest='dest.bin',
        source_file=src,
        member_name='member-a',
        mapping=TemplateMapping(source_template='source.bin'),
    )
    root_session = _make_session(tmp_path)

    records, result = _apply_winners(
        {'dest.bin': winner},
        root_session,
        check_only=False,
    )

    assert records[0].path == 'dest.bin'
    assert result == {'dest.bin': 'written'}
    assert (tmp_path / 'dest.bin').read_bytes() == b'\xff\xfe\x00binary'


def test_apply_winners_check_only_handles_unreadable_text_dest(tmp_path: Path) -> None:
    """Check mode should report differs when destination text cannot be decoded."""
    src = tmp_path / 'source.txt'
    src.write_text('plain text\n', encoding='utf-8')
    (tmp_path / 'dest.txt').write_bytes(b'\xff\xfe\x00binary')

    winner = PromotionWinner(
        dest='dest.txt',
        source_file=src,
        member_name='member-a',
        mapping=TemplateMapping(source_template='source.txt'),
    )
    root_session = _make_session(tmp_path)

    records, result = _apply_winners(
        {'dest.txt': winner},
        root_session,
        check_only=True,
    )

    assert records[0].path == 'dest.txt'
    assert result == {'dest.txt': 'differs'}


def test_apply_winners_promoted_text_write_preserves_mode(tmp_path: Path) -> None:
    """Text hydration writes should preserve executable mode from promoted source."""
    src = tmp_path / 'member-script.sh'
    src.write_text('#!/bin/bash\necho new\n', encoding='utf-8')
    src.chmod(0o755)
    dest = tmp_path / 'script.sh'
    dest.write_text('#!/bin/bash\necho old\n', encoding='utf-8')
    dest.chmod(0o644)

    winner = PromotionWinner(
        dest='script.sh',
        source_file=src,
        member_name='member-a',
        mapping=TemplateMapping(source_template='script.sh'),
    )
    root_session = _make_session(tmp_path)

    records, result = _apply_winners(
        {'script.sh': winner},
        root_session,
        check_only=False,
    )

    assert records[0].path == 'script.sh'
    assert result == {'script.sh': 'written'}
    assert dest.read_text(encoding='utf-8') == '#!/bin/bash\necho new\n'
    assert dest.stat().st_mode & 0o111


def test_post_process_promoted_files_updates_changed_outputs(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Promoted post-process should copy normalized content back to project files."""
    root_session = _make_session(tmp_path)
    root_session.config.post_process = ['fake-format']
    root_session.promoted_apply_result = {'out.md': 'unchanged'}

    out = tmp_path / 'out.md'
    out.write_text('before\n', encoding='utf-8')

    def _fake_run_post_process(_commands: object, cwd: Path) -> None:
        (cwd / 'out.md').write_text('after\n', encoding='utf-8')

    mocker.patch(
        'repolish.commands.apply.coordinator.run_post_process',
        side_effect=_fake_run_post_process,
    )

    _post_process_promoted_files(root_session, tmp_path)

    assert out.read_text(encoding='utf-8') == 'after\n'
    assert root_session.promoted_apply_result == {'out.md': 'written'}


def test_run_root_pass_triggers_promoted_post_process_in_apply_mode(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Root pass should run promoted post-process after successful apply."""
    mocker.patch(
        'repolish.commands.apply.coordinator._apply_promotion_pass',
        return_value=0,
    )
    mocker.patch(
        'repolish.commands.apply.coordinator.apply_session',
        return_value=0,
    )
    post_mock = mocker.patch(
        'repolish.commands.apply.coordinator._post_process_promoted_files',
    )

    root_session = _make_session(tmp_path)
    opts = CoordinateOptions(check_only=False, skip_post_process=False)
    rc = _run_root_pass([], root_session, tmp_path, [], opts)

    assert rc == 0
    post_mock.assert_called_once_with(root_session, tmp_path)


def test_run_root_pass_skips_promoted_post_process_in_check_mode(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """Check mode must not execute promoted post-process commands."""
    mocker.patch(
        'repolish.commands.apply.coordinator._apply_promotion_pass',
        return_value=2,
    )
    mocker.patch(
        'repolish.commands.apply.coordinator.apply_session',
        return_value=0,
    )
    post_mock = mocker.patch(
        'repolish.commands.apply.coordinator._post_process_promoted_files',
    )

    root_session = _make_session(tmp_path)
    opts = CoordinateOptions(check_only=True, skip_post_process=False)
    rc = _run_root_pass([], root_session, tmp_path, [], opts)

    assert rc == 2
    post_mock.assert_not_called()


def test_promoted_differs_returns_true_when_dest_text_unreadable(
    tmp_path: Path,
) -> None:
    """Unreadable destination text should be treated as differing."""
    source = tmp_path / 'source.txt'
    source.write_text('hello\n', encoding='utf-8')
    dest = tmp_path / 'dest.txt'
    dest.mkdir()

    winner = PromotionWinner(
        dest='dest.txt',
        source_file=source,
        member_name='member-a',
        mapping=TemplateMapping(source_template='source.txt'),
    )
    ctx = PromotedWriteContext(
        winner=winner,
        dest_file=dest,
        rendered_text='hello\n',
        source_mode=None,
    )

    assert _promoted_differs(ctx) is True


def test_sync_post_processed_promoted_files_skips_missing_and_unchanged(
    tmp_path: Path,
) -> None:
    """Sync helper should no-op when temp output is missing or unchanged."""
    root_dir = tmp_path / 'root'
    tmp_dir = tmp_path / 'tmp'
    root_dir.mkdir()
    tmp_dir.mkdir()

    (root_dir / 'missing.txt').write_text('same\n', encoding='utf-8')
    (root_dir / 'same.txt').write_text('same\n', encoding='utf-8')
    (tmp_dir / 'same.txt').write_text('same\n', encoding='utf-8')

    promoted_result = {
        'missing.txt': 'written',
        'same.txt': 'unchanged',
    }

    _sync_post_processed_promoted_files(
        ['missing.txt', 'same.txt'],
        root_dir,
        tmp_dir,
        promoted_result,
    )

    assert promoted_result == {
        'missing.txt': 'written',
        'same.txt': 'unchanged',
    }
