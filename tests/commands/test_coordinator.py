"""Tests for coordinator promotion helpers and monorepo orchestration paths."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

from repolish.commands.apply.coordinator import (
    PromotionWinner,
    _apply_promotion_pass,
    _apply_winners,
    _run_apply_phase,
    _run_root_pass,
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
