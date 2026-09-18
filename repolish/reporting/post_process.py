"""Produce the post-process summary tree nodes.

One group per session that ran post-process commands (the member name, the
root, or the standalone directory), one node per command with its outcome
marker. The group label carries the single `[details]` link to the session's
report (every command in the group shares that file). Sessions that ran
nothing contribute no group, so the tree is silent when post-process is
unused.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from rich.text import Text

from repolish.postprocess.models import CommandOutcome, PostProcessRun
from repolish.postprocess.report import format_duration
from repolish.reporting.nodes import (
    Status,
    SummaryNode,
    details_link,
    stat_suffix,
    status_prefix,
)

if TYPE_CHECKING:
    from repolish.commands.apply.options import ResolvedSession


def session_label(session: 'ResolvedSession') -> str:
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


def _group_suffix_text(label: str, outcomes: Sequence[CommandOutcome]) -> Text:
    """Compose a group label with its ok/failed/not-run counts."""
    text = Text(label, style='bold')
    ok = sum(1 for o in outcomes if o.status == 'ok')
    failed = sum(1 for o in outcomes if o.status == 'failed')
    not_run = sum(1 for o in outcomes if o.status == 'not_run')
    parts = [
        f'[green]{ok} ok[/green]',
        f'[red]{failed} failed[/red]',
        f'[yellow]{not_run} not run[/yellow]',
    ]
    parts = [part for count, part in zip((ok, failed, not_run), parts, strict=False) if count]
    if parts:
        stat_suffix(text, parts)
    return text


def _command_text(outcome: CommandOutcome) -> Text:
    """One command row: marker, the raw argv as written, and the outcome."""
    text = Text()
    if outcome.status == 'ok':
        text.append_text(status_prefix(Status.OK))
    elif outcome.status == 'failed':
        text.append_text(status_prefix(Status.FAIL))
    else:
        text.append_text(status_prefix(Status.SKIP))
    text.append(' '.join(outcome.raw) or ' '.join(outcome.argv))
    if outcome.status == 'ok':
        text.append(
            f'  ok ({format_duration(outcome.duration_ms)})',
            style='dim',
        )
    elif outcome.status == 'not_run':
        text.append('  not run (previous command failed)', style='dim yellow')
    else:
        note = outcome.error or f'exit {outcome.returncode}'
        text.append(f'  FAILED {note}', style='red')
    return text


def _run_children(run: PostProcessRun) -> list[SummaryNode]:
    return [SummaryNode(label=_command_text(outcome)) for outcome in run.outcomes]


def post_process_nodes(
    sessions: Sequence['ResolvedSession'],
) -> list[SummaryNode]:
    """Build the post-process summary groups for every session that ran commands.

    The session's report file is shared by every command in the group, so the
    group label carries the single `[details]` link; command rows stay plain.
    A promoted-files run (root monorepo pass) nests as its own labeled
    subgroup with a details link of its own, since it writes its own report.
    """
    nodes: list[SummaryNode] = []
    for session in sessions:
        if not session.post_process_runs:
            continue
        all_outcomes = [outcome for _label, run in session.post_process_runs for outcome in run.outcomes]
        group_label = _group_suffix_text(session_label(session), all_outcomes)
        group = SummaryNode(label=group_label)
        for (label, run), report_path in zip(
            session.post_process_runs,
            session.post_process_reports,
            strict=True,
        ):
            if label == 'session':
                details_link(group_label, report_path)
                group.children.extend(_run_children(run))
            else:
                sub_label = _group_suffix_text(label, run.outcomes)
                details_link(sub_label, report_path)
                group.children.append(
                    SummaryNode(
                        label=sub_label,
                        children=_run_children(run),
                    ),
                )
        nodes.append(group)
    return nodes
