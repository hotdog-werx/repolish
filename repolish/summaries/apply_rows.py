"""Derivation for the apply summary tree: `SummarySession` in, rows out.

The state-decision half of the summary contract. Every question about what
happened to a file, copy, symlink, or promoted file in a run is answered
here and expressed as a typed row from `repolish.summaries.rows`; a
renderer then only draws. Nothing in this module imports rich or prints:
it is pure derivation, unit-testable with a hand-built session.

The input type is the `SummarySession` protocol from
`repolish.summaries.contract`: the pipeline's `ResolvedSession` satisfies
it structurally, and the functions never need that class at runtime, so
summaries stays free of import cycles with `commands.apply`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from repolish.config.paused import is_paused
from repolish.providers._log import logger
from repolish.providers.models import (
    BaseContext,
    FileMode,
    FileRecord,
    FileValidatorEntry,
    FileValidatorSpec,
)
from repolish.providers.models.files import ValidationStatus
from repolish.summaries.rows import (
    AppliedStats,
    CopyRow,
    CopyState,
    FileRow,
    FileState,
    InsertionLine,
    InsertionState,
    PendingStats,
    PromotedRow,
    PromotedState,
    ProviderBranch,
    SessionGroup,
    SymlinkRow,
    ValidatorLine,
    ValidatorState,
)
from repolish.utils import path_slug

if TYPE_CHECKING:
    from collections.abc import Sequence

    from repolish.commands.apply.options import InsertionFileResult
    from repolish.config.models.provider import ProviderCopy, ProviderSymlink
    from repolish.summaries.contract import SummarySession


# Apply-result status strings -> file states. Anything else fails loudly in
# `file_state_from_status` instead of silently rendering a green check mark.
_APPLY_STATUS_TO_STATE: dict[str, FileState] = {
    'written': FileState.WRITTEN,
    'unchanged': FileState.UNCHANGED,
    'deleted': FileState.DELETED,
    'drift': FileState.DRIFT,
}

_PROMOTED_STATUS_TO_STATE: dict[str | None, PromotedState] = {
    None: PromotedState.WRITTEN,
    'written': PromotedState.WRITTEN,
    'unchanged': PromotedState.UNCHANGED,
    'differs': PromotedState.DIFFERS,
    'overridden_by_root': PromotedState.OVERRIDDEN_BY_ROOT,
    'paused': PromotedState.PAUSED,
    'suppressed': PromotedState.SUPPRESSED,
}


def file_state_from_status(status: str | None) -> FileState:
    """Map an apply-result status string to its file state.

    ``None`` (no status recorded: clean in check mode, or validator-shaped
    rows) maps to `FileState.OK`. Unknown strings raise: they are produced
    by our own apply pipeline, so an unmapped value is a bug, not a state.
    """
    if status is None:
        return FileState.OK
    try:
        return _APPLY_STATUS_TO_STATE[status]
    except KeyError:
        msg = f'unknown apply-result status: {status!r}'
        raise ValueError(msg) from None


def skip_state(
    record: FileRecord,
    session: SummarySession,
) -> FileState | None:
    """Return the state of a file that was not applied, or None if it was.

    Checks in order: suppressed template, paused file, then auto-staging
    disabled for a root monorepo pass (files not in ``create_file_mappings``
    are never written to the root).
    """
    if record.mode == FileMode.SUPPRESS:
        if record.path in session.providers.disabled_file_mappings:
            return FileState.DISABLED
        return FileState.SUPPRESSED
    if is_paused(record.path, frozenset(session.config.paused_files)):
        return FileState.PAUSED
    if (
        session.global_context.workspace.mode == 'root'
        and record.mode
        not in (
            FileMode.DELETE,
            FileMode.KEEP,
            FileMode.SUPPRESS,
        )
        and record.path not in session.providers.file_mappings
        and record.path not in session.providers.file_validators
        and record.path not in session.providers.file_insertions
    ):
        return FileState.ROOT_SKIPPED
    return None


def _validator_entry_enabled(entry: FileValidatorEntry) -> bool:
    """Return whether the entry should still execute."""
    if isinstance(entry, FileValidatorSpec):
        return bool(entry.options.enabled)
    return True


def _is_validator_only_not_staged(
    record: FileRecord,
    session: SummarySession,
) -> bool:
    """Return True when a validator is attached to a file that was never staged.

    This covers provider-only validation targets such as existing project files
    with no `file_mappings` entry. Those files are still meaningful to the
    provider, but they are not materialized in the render stage.
    """
    return bool(
        record.path in session.providers.file_validators
        and not (session.apply_result and record.path in session.apply_result)
        and record.path not in session.providers.file_mappings
        and record.path not in session.providers.template_sources,
    )


def _validator_file_owner(
    record: FileRecord,
    session: SummarySession,
) -> str | None:
    """Return the non-matching provider that owns the file path, if any.

    Only considers providers that own the file via file_mappings or template_sources,
    not just via insertions. This avoids false "owned by" messages for project files
    that multiple providers add insertions to.
    """
    # Check if the file has a "real" owner (via file_mappings or template_sources)
    real_owners = {
        r.owner
        for r in session.providers.file_records
        if r.path == record.path and r.owner != record.owner and r.source is not None
    }
    if len(real_owners) == 1:
        return next(iter(real_owners))
    return None


def _is_insertion_only_not_staged(
    record: FileRecord,
    session: SummarySession,
) -> bool:
    """Return True when insertions target a file that was never staged."""
    # Check if this record's provider has actual insertions (total_blocks > 0)
    provider_has_insertions = (
        record.owner in session.provider_insertion_results
        and record.path in session.provider_insertion_results.get(record.owner, {})
        and session.provider_insertion_results[record.owner][record.path].total_blocks > 0
    )

    # Check if file_insertions has actual functions (non-empty dict)
    file_insertions_has_functions = (
        record.path in session.providers.file_insertions and session.providers.file_insertions[record.path]
    )

    return bool(
        (provider_has_insertions or file_insertions_has_functions)
        and not (session.apply_result and record.path in session.apply_result)
        and record.path not in session.providers.file_mappings
        and record.path not in session.providers.template_sources,
    )


def _insertion_only_label(session: SummarySession) -> str:
    """Label for an insertion-only file that was never staged.

    Without a provider filter every configured provider ran, so no provider
    claimed the file and it is confidently developer-owned. Under a provider
    filter the true owner may simply be an excluded provider, so the weaker
    "possibly provider-owned" applies.
    """
    if session.provider_filter is not None:
        return 'possibly provider-owned'
    return 'developer owned'


def _insertion_line_from_result(
    result: InsertionFileResult,
) -> InsertionLine:
    """Turn one insertion execution result into an insertion line row."""
    succeeded = result.total_blocks - result.failed_blocks - result.disabled_blocks
    return InsertionLine(
        state=InsertionState.OK if result.failed_blocks == 0 else InsertionState.FAILED,
        succeeded=succeeded,
        failed=result.failed_blocks,
        disabled=result.disabled_blocks,
        link=Path(result.report_path) if result.report_path else None,
    )


def insertion_line(
    record: FileRecord,
    session: SummarySession,
) -> InsertionLine | None:
    """Return the insertion status line for the current provider, if any.

    When the record's owner has insertion results, show only that provider's
    insertions. This avoids duplicating output when a file appears under
    multiple provider branches.
    """
    provider_alias = record.owner

    # Check if this provider has insertion results for this file
    if provider_alias in session.provider_insertion_results:
        file_results = session.provider_insertion_results[provider_alias]
        if record.path in file_results:
            result = file_results[record.path]
            if result.total_blocks > 0:
                return _insertion_line_from_result(result)
            return None

    # Fall back to aggregated result
    insertion_result = session.insertion_results.get(record.path)
    if insertion_result is not None and insertion_result.total_blocks > 0:
        return _insertion_line_from_result(insertion_result)
    return None


def _validator_lines(
    record: FileRecord,
    session: SummarySession,
) -> tuple[ValidatorLine, ...]:
    """Build one line per validator registered on the record's file."""
    validation_results = session.validation_results.get(record.path, {}) if session.validation_results else {}
    file_validators = session.providers.file_validators.get(record.path, {})
    lines: list[ValidatorLine] = []
    for validator_name in sorted(file_validators):
        entry = file_validators[validator_name]
        result = validation_results.get(validator_name)
        if not _validator_entry_enabled(entry):
            lines.append(
                ValidatorLine(
                    name=validator_name,
                    state=ValidatorState.DISABLED,
                    message='disabled',
                ),
            )
        elif result is None:
            # The session records only non-PASS outcomes, so no recorded
            # result is a pass — never an unknown or skipped execution
            # (paused and disabled files never reach this line).
            lines.append(
                ValidatorLine(name=validator_name, state=ValidatorState.PASS),
            )
        elif result.status == ValidationStatus.WARNING:
            lines.append(
                ValidatorLine(
                    name=validator_name,
                    state=ValidatorState.WARNING,
                    message=result.message,
                ),
            )
        else:
            lines.append(
                ValidatorLine(
                    name=validator_name,
                    state=ValidatorState.ERROR,
                    message=result.message,
                ),
            )
    return tuple(lines)


def _validator_file_row(
    record: FileRecord,
    session: SummarySession,
) -> FileRow:
    """Row for a file whose validators are shown beneath it."""
    other_owner = _validator_file_owner(record, session)
    if _is_validator_only_not_staged(record, session) or other_owner is not None:
        state = FileState.VALIDATOR_ONLY
    else:
        state = FileState.OK
    if other_owner:
        owner_note = f'owned by {other_owner}'
    elif _is_validator_only_not_staged(record, session):
        owner_note = 'developer owned'
    else:
        owner_note = ''
    report = session.validation_reports.get(record.path)
    return FileRow(
        path=record.path,
        state=state,
        owner_note=owner_note,
        validators=_validator_lines(record, session),
        insertion=insertion_line(record, session),
        validator_report=Path(report) if report else None,
    )


def _file_source(record: FileRecord) -> str:
    """The `←` annotation for a staged file: its template source, if any."""
    source = record.source if record.source and record.source != record.path else ''
    if not source and record.overlay_dir:
        return f'{record.overlay_dir}/'
    return source


def _insertion_owner_note(
    record: FileRecord,
    session: SummarySession,
    other_owner: str | None,
) -> str:
    """Ownership hedge for a staged file another provider also claims."""
    if other_owner:
        return f'owned by {other_owner}'
    if _is_insertion_only_not_staged(record, session):
        return _insertion_only_label(session)
    return ''


def _status_file_row(record: FileRecord, session: SummarySession) -> FileRow:
    """Row for a normal staged file: apply status, source, and mode."""
    other_owner = _validator_file_owner(record, session)
    if _is_insertion_only_not_staged(record, session) or other_owner is not None:
        state = FileState.INSERTION_ONLY
    else:
        status = session.apply_result.get(record.path) if session.apply_result else None
        state = file_state_from_status(status)

    mode_val = record.mode.value
    mode_note = '' if mode_val in ('regular', 'delete') else mode_val
    source = _file_source(record)
    owner_note = _insertion_owner_note(record, session, other_owner)

    debug_dir = session.config.config_dir / '.repolish' / '_'
    link = (
        debug_dir / 'file-ctx' / f'file-context.{path_slug(record.path)}.json'
        if record.mode in (FileMode.REGULAR, FileMode.CREATE_ONLY)
        else None
    )
    return FileRow(
        path=record.path,
        state=state,
        source=source,
        mode_note=mode_note,
        owner_note=owner_note,
        insertion=insertion_line(record, session),
        link=link,
    )


def file_row(
    record: FileRecord,
    session: SummarySession,
) -> FileRow:
    """Build the row for one file record, dispatching on its shape.

    Skipped files (paused, suppressed, root-mode) carry only their state;
    files with validators owned by this provider get validator lines beneath
    them; everything else is a normal status row.
    """
    state = skip_state(record, session)
    if state is not None:
        return FileRow(path=record.path, state=state)
    file_validators = session.providers.file_validators.get(record.path, {})
    if file_validators:
        validator_provider = session.providers.validator_sources.get(
            record.path,
        )
        validator_alias = (
            session.pid_to_alias.get(validator_provider, validator_provider)
            if validator_provider is not None
            else None
        )
        if validator_alias is None or validator_alias == record.owner:
            return _validator_file_row(record, session)
    return _status_file_row(record, session)


def symlink_row(sl: ProviderSymlink) -> SymlinkRow:
    """Build the row for one symlink entry."""
    return SymlinkRow(target=str(sl.target), source=str(sl.source))


def copy_row(
    copy: ProviderCopy,
    paused_paths: frozenset[str],
    paused_files: frozenset[str],
) -> CopyRow:
    """Build the row for one copy entry: active, paused, or partial.

    *paused_paths* comes from `apply_copies` (or the check-mode
    `held_back_copy_targets` computation) — the destinations actually held
    back. Whole-entry pauses are still detected via the pause matcher so
    check-only runs report them identically; paths under `<target>/` mean
    files inside a directory copy were skipped (partially paused folder).
    """
    target = copy.target.as_posix()
    if target in paused_paths or is_paused(target, paused_files):
        state = CopyState.PAUSED
    elif any(p.startswith(f'{target}/') for p in paused_paths):
        state = CopyState.PARTIALLY_PAUSED
    else:
        state = CopyState.ACTIVE
    return CopyRow(target=target, source=str(copy.source), state=state)


def promoted_row(
    record: FileRecord,
    promoted_apply_result: dict[str, str],
) -> PromotedRow:
    """Build the row for one file promoted from a member session to the root."""
    status = promoted_apply_result.get(record.path) if promoted_apply_result else None
    try:
        state = _PROMOTED_STATUS_TO_STATE[status]
    except KeyError:
        msg = f'unknown promoted-result status: {status!r}'
        raise ValueError(msg) from None
    return PromotedRow(
        path=record.path,
        state=state,
        promoted_from=record.promoted_from or '',
        overridden_by=record.overridden_by or '',
    )


def _applied_stats(
    records: Sequence[FileRecord],
    symlinks: Sequence[ProviderSymlink],
    copies: Sequence[ProviderCopy],
    session: SummarySession,
) -> AppliedStats:
    """Count apply outcomes over a provider's records for its label suffix."""
    record_paths = {r.path for r in records}
    apply_result = session.apply_result

    def _count(status: str) -> int:
        return sum(1 for p in record_paths if apply_result.get(p) == status)

    skipped = sum(1 for r in records if skip_state(r, session) is not None)
    return AppliedStats(
        written=_count('written'),
        unchanged=_count('unchanged'),
        deleted=_count('deleted'),
        drift=_count('drift'),
        skipped=skipped,
        symlinks=len(symlinks),
        copies=len(copies),
    )


def _pending_stats(
    records: Sequence[FileRecord],
    symlinks: Sequence[ProviderSymlink],
    copies: Sequence[ProviderCopy],
    session: SummarySession,
) -> PendingStats:
    """Count pre-apply dispositions for a provider's label suffix."""
    skipped = sum(1 for r in records if skip_state(r, session) is not None)
    total = len(records) + len(symlinks)
    return PendingStats(
        applied=total - skipped,
        not_applied=skipped,
        copies=len(copies),
    )


def _role_label(ctx: object) -> str:
    """Return a display label for the provider's monorepo role."""
    try:
        if isinstance(ctx, BaseContext):
            info = ctx.repolish.provider.session
            if info.mode == 'root':
                return 'root'
            if info.mode == 'member' and info.member_name:
                return f'member: {info.member_name}'
    except Exception as exc:  # noqa: BLE001  # pragma: no cover — defensive: BaseContext.repolish is always valid; only a deeply broken ctx object would trigger this
        logger.warning(  # pragma: no cover
            'role_label_exception',
            error=str(exc),
            ctx_type=type(ctx).__name__,
        )
    return 'standalone'


def _classify_aliases(
    session: SummarySession,
) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Split session aliases into root, per-member, and standalone groups."""
    root_aliases: list[str] = []
    member_aliases: dict[str, list[str]] = {}
    standalone_aliases: list[str] = []
    for alias in session.aliases:
        pid = session.alias_to_pid.get(alias)
        ctx = session.providers.provider_contexts.get(pid) if pid else None
        label = _role_label(ctx)
        if label == 'root':
            root_aliases.append(alias)
        elif label.startswith('member:'):
            member_name = label[len('member: ') :]
            member_aliases.setdefault(member_name, []).append(alias)
        else:
            standalone_aliases.append(alias)
    return root_aliases, member_aliases, standalone_aliases


def _records_by_owner(session: SummarySession) -> dict[str, list[FileRecord]]:
    """Group file records by the provider alias that owns them."""
    records_by_owner: dict[str, list[FileRecord]] = {}
    for record in session.providers.file_records:
        records_by_owner.setdefault(record.owner, []).append(record)
    return records_by_owner


def _attach_validator_owner_records(
    records_by_owner: dict[str, list[FileRecord]],
    session: SummarySession,
) -> None:
    """Add validator-owned entries beneath the provider that declared them."""
    for dest, validator_provider in session.providers.validator_sources.items():
        validator_alias = session.pid_to_alias.get(
            validator_provider,
            validator_provider,
        )
        alias_records = records_by_owner.setdefault(validator_alias, [])
        if dest in session.providers.file_validators and not any(record.path == dest for record in alias_records):
            alias_records.append(
                FileRecord(
                    path=dest,
                    mode=FileMode.REGULAR,
                    owner=validator_alias,
                    source=None,
                ),
            )


def _attach_insertion_owner_records(
    records_by_owner: dict[str, list[FileRecord]],
    session: SummarySession,
) -> None:
    """Add insertion-owned entries beneath each provider that declared insertions.

    When multiple providers target the same file with insertions, the file appears
    under each provider showing that provider's insertion count.
    """
    for dest, provider_ids in session.providers.insertion_sources.items():
        for provider_id in provider_ids:
            provider_alias = session.pid_to_alias.get(provider_id, provider_id)
            # Only add if this provider actually has insertions (total_blocks > 0)
            has_insertions = (
                provider_alias in session.provider_insertion_results
                and dest in session.provider_insertion_results[provider_alias]
                and session.provider_insertion_results[provider_alias][dest].total_blocks > 0
            )
            alias_records = records_by_owner.setdefault(provider_alias, [])
            # Only add if not already present for this provider
            if has_insertions and not any(record.path == dest for record in alias_records):
                alias_records.append(
                    FileRecord(
                        path=dest,
                        mode=FileMode.REGULAR,
                        owner=provider_alias,
                        source=None,
                    ),
                )


def _provider_branch(
    alias: str,
    records_by_owner: dict[str, list[FileRecord]],
    session: SummarySession,
    debug_dir: Path,
) -> ProviderBranch:
    """Build one provider's branch: its rows and its label stats."""
    from repolish.commands.apply.debug import debug_file_slug  # noqa: PLC0415

    records = records_by_owner.get(alias, [])
    syms = session.resolved_symlinks.get(alias, [])
    copies = session.resolved_copies.get(alias, [])
    rows: list[FileRow | SymlinkRow | CopyRow] = [file_row(record, session) for record in records]
    rows.extend(symlink_row(sl) for sl in syms)
    paused_paths = frozenset(session.paused_copies.get(alias, ()))
    paused_files = frozenset(session.config.paused_files)
    rows.extend(copy_row(cp, paused_paths, paused_files) for cp in copies)
    if session.apply_result:
        stats: AppliedStats | PendingStats = _applied_stats(
            records,
            syms,
            copies,
            session,
        )
    else:
        stats = _pending_stats(records, syms, copies, session)
    pid = session.alias_to_pid.get(alias)
    ctx = session.providers.provider_contexts.get(pid) if pid else None
    version = ctx.repolish.provider.version if ctx is not None and isinstance(ctx, BaseContext) else None
    slug = debug_file_slug(ctx, alias)
    return ProviderBranch(
        alias=alias,
        version=version,
        rows=tuple(rows),
        stats=stats,
        link=debug_dir / f'provider-context.{slug}.json',
    )


def session_groups(session: SummarySession) -> list[SessionGroup]:
    """Build one row group set for a session, grouped by provider role."""
    debug_dir = session.config.config_dir / '.repolish' / '_'
    records_by_owner = _records_by_owner(session)
    _attach_validator_owner_records(records_by_owner, session)
    _attach_insertion_owner_records(records_by_owner, session)
    root_aliases, member_aliases, standalone_aliases = _classify_aliases(
        session,
    )

    groups: list[SessionGroup] = []
    if root_aliases:
        promoted = tuple(promoted_row(record, session.promoted_apply_result) for record in session.promoted_records)
        groups.append(
            SessionGroup(
                title='Root',
                branches=tuple(
                    _provider_branch(
                        alias,
                        records_by_owner,
                        session,
                        debug_dir,
                    )
                    for alias in root_aliases
                ),
                promoted=promoted,
            ),
        )

    for member_name, m_aliases in member_aliases.items():
        groups.append(
            SessionGroup(
                title=f'Member: {member_name}',
                branches=tuple(
                    _provider_branch(
                        alias,
                        records_by_owner,
                        session,
                        debug_dir,
                    )
                    for alias in m_aliases
                ),
            ),
        )

    if standalone_aliases:
        groups.append(
            SessionGroup(
                title='Standalone',
                branches=tuple(
                    _provider_branch(
                        alias,
                        records_by_owner,
                        session,
                        debug_dir,
                    )
                    for alias in standalone_aliases
                ),
            ),
        )
    return groups


def apply_summary_rows(
    sessions: Sequence[SummarySession],
) -> list[SessionGroup]:
    """Merge every session's groups (Root / Member / Standalone) into one row list."""
    return [group for session in sessions for group in session_groups(session)]
