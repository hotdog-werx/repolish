"""Derivation for the post-process summary: session runs in, rows out.

One group per session that ran post-process commands (the member name,
the root, or the standalone directory), one command row per command with
its outcome state. The group carries the single link to the session's
report (every command in the group shares that file); runs with their own
report (a promoted-files pass) nest as labeled subgroups. Sessions that
ran nothing contribute no group, so the tree is silent when post-process
is unused. Rendering lives in `repolish.reporting.leaves`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repolish.summaries.rows import CommandRow, CommandState, PostProcessGroup

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from repolish.postprocess.models import CommandOutcome, PostProcessRun
    from repolish.summaries.contract import PostProcessSession


# Outcome status strings -> command states. Anything else fails loudly:
# the runner produces these three values, so an unmapped one is a bug.
_COMMAND_STATE: dict[str, CommandState] = {
    'ok': CommandState.OK,
    'failed': CommandState.FAILED,
    'not_run': CommandState.NOT_RUN,
}


def session_label(session: PostProcessSession) -> str:
    """Name a session after its directory role (member name, root, or dir).

    Used by the post-process group label and the phase-timings footer so both
    surfaces call a session the same thing.
    """
    mode = session.global_context.workspace.mode
    if mode == 'member':
        for ctx in session.providers.provider_contexts.values():
            name = ctx.repolish.provider.session.member_name
            if name and name != '_root':
                return name
    return session.config.config_dir.name


def _command_row(outcome: CommandOutcome) -> CommandRow:
    """Turn one command outcome into a command row."""
    try:
        state = _COMMAND_STATE[outcome.status]
    except KeyError:
        msg = f'unknown post-process outcome status: {outcome.status!r}'
        raise ValueError(msg) from None
    return CommandRow(
        raw=' '.join(outcome.raw) or ' '.join(outcome.argv),
        state=state,
        duration_ms=outcome.duration_ms,
        error=outcome.error,
        returncode=outcome.returncode,
    )


def _counts(outcomes: Sequence[CommandOutcome]) -> tuple[int, int, int]:
    """Return the (ok, failed, not_run) counts for a group label suffix."""
    ok = sum(1 for o in outcomes if o.status == 'ok')
    failed = sum(1 for o in outcomes if o.status == 'failed')
    not_run = sum(1 for o in outcomes if o.status == 'not_run')
    return ok, failed, not_run


def _labeled_subgroup(
    label: str,
    run: PostProcessRun,
    report_path: Path,
) -> PostProcessGroup:
    """Build one labeled subgroup with its own report link and counts."""
    ok, failed, not_run = _counts(run.outcomes)
    return PostProcessGroup(
        label=label,
        link=report_path,
        commands=tuple(_command_row(o) for o in run.outcomes),
        ok=ok,
        failed=failed,
        not_run=not_run,
    )


def post_process_rows(
    sessions: Sequence[PostProcessSession],
) -> list[PostProcessGroup]:
    """Build one group row per session that ran post-process commands."""
    groups: list[PostProcessGroup] = []
    for session in sessions:
        if not session.post_process_runs:
            continue
        all_outcomes = [outcome for _label, run in session.post_process_runs for outcome in run.outcomes]
        ok, failed, not_run = _counts(all_outcomes)
        session_link: Path | None = None
        commands: tuple[CommandRow, ...] = ()
        subgroups: list[PostProcessGroup] = []
        for (label, run), report_path in zip(
            session.post_process_runs,
            session.post_process_reports,
            strict=True,
        ):
            if label == 'session':
                session_link = report_path
                commands = tuple(_command_row(o) for o in run.outcomes)
            else:
                subgroups.append(_labeled_subgroup(label, run, report_path))
        groups.append(
            PostProcessGroup(
                label=session_label(session),
                link=session_link,
                commands=commands,
                subgroups=tuple(subgroups),
                ok=ok,
                failed=failed,
                not_run=not_run,
            ),
        )
    return groups
