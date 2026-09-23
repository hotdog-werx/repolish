"""Leaf renderers: rows in, `SummaryNode` trees out.

The drawing half of the summary contract. Every glyph, color, note, and
hyperlink a summary prints is applied here, sourced from `MARKERS` in
`repolish.reporting.markers` via `marker_for`; renderers never invent a
marker or fall back to a default. They consume row data only: no session
objects, no state decisions — the rows come from `repolish.summaries`.
"""

from collections.abc import Sequence
from pathlib import Path

from rich.text import Text

from repolish.console import supports_hyperlinks
from repolish.postprocess.report import format_duration
from repolish.reporting.markers import marker_for
from repolish.reporting.nodes import SummaryNode, details_link, stat_suffix
from repolish.summaries.rows import (
    AppliedStats,
    CommandRow,
    CommandState,
    CopyRow,
    CopyState,
    FileRow,
    InsertionLine,
    PendingStats,
    PostProcessGroup,
    PromotedRow,
    ProviderBranch,
    SessionGroup,
    SymlinkRow,
    ValidatorLine,
    ValidatorState,
)

# rich styles for a file mode note, keyed by FileMode value.
MODE_STYLES: dict[str, str] = {
    'regular': 'green',
    'create_only': 'yellow',
    'delete': 'red',
    'keep': 'cyan',
}


def _link_style(link: Path | None, prefix: str = '') -> str:
    """Return the hyperlink style for *link*, prefixed by *prefix*.

    Hyperlink support off (or no link): just the prefix (possibly empty), so
    unlinked rows keep their plain or bold styling.
    """
    if link is not None and supports_hyperlinks:
        style = f'link file://{link.absolute()}'
        return f'{prefix} {style}' if prefix else style
    return prefix


def _validator_text(line: ValidatorLine) -> str:
    """One validator line's text: the name alone, or name plus detail."""
    if line.state is ValidatorState.PASS:
        return line.name
    return f'{line.name}: {line.message}'


def _append_validator_lines(node: Text, row: FileRow) -> None:
    """Append the `validators:` block with one line per validator."""
    node.append('\n  validators:', style='dim green')
    for line in row.validators:
        marker = marker_for(line.state)
        node.append(
            f'\n    - {marker.glyph} {_validator_text(line)}',
            style=marker.style,
        )
    if row.validator_report is not None:
        details_link(node, row.validator_report)


def _append_insertion_line(node: Text, line: InsertionLine) -> None:
    """Append the `insertions:` status line with its details link."""
    marker = marker_for(line.state)
    status_label = 'ok' if line.state.value == 'ok' else 'failed'
    disabled_segment = f', {line.disabled} disabled' if line.disabled else ''
    node.append(
        f'\n  insertions: {marker.glyph} {status_label} ({line.succeeded} ok, {line.failed} failed{disabled_segment})',
        style=marker.style,
    )
    if line.link is not None:
        details_link(node, line.link)


def render_file_row(row: FileRow) -> SummaryNode:
    """Draw one file row: marker, path, notes, and any detail lines."""
    node = Text()
    marker = marker_for(row.state)
    node.append(marker.glyph, style=marker.style)
    node.append(row.path, style=_link_style(row.link))
    if row.mode_note:
        style = MODE_STYLES.get(row.mode_note, '')
        node.append(f'  {row.mode_note}', style=f'dim {style}'.strip())
    if row.source:
        node.append(f'  ← {row.source}', style='dim')
    if row.owner_note:
        node.append(f'  {row.owner_note}', style='dim yellow')
    if marker.note:
        node.append(f'  {marker.note}', style=marker.note_styled)
    if row.validators:
        _append_validator_lines(node, row)
    if row.insertion is not None:
        _append_insertion_line(node, row.insertion)
    return SummaryNode(label=node)


def render_symlink_row(row: SymlinkRow) -> SummaryNode:
    """Draw one symlink row: blue arrow, target, dim source."""
    node = Text()
    node.append('↗ ', style='blue')
    node.append(row.target)
    node.append(f'  → {row.source}', style='dim')
    return SummaryNode(label=node)


def render_copy_row(row: CopyRow) -> SummaryNode:
    """Draw one copy row: clipboard/pause marker, target, dim source, note."""
    marker = marker_for(row.state)
    node = Text()
    node.append(marker.glyph, style=marker.style)
    if row.state is CopyState.ACTIVE:
        node.append(row.target)
        node.append(f'  ← {row.source}', style='dim')
    else:
        node.append(row.target, style='yellow')
        node.append(f'  ← {row.source} ', style='dim')
        node.append(marker.note, style=marker.note_styled)
    return SummaryNode(label=node)


def render_promoted_row(row: PromotedRow) -> SummaryNode:
    """Draw one promoted-file row: marker, path, provenance annotation."""
    marker = marker_for(row.state)
    node = Text()
    node.append(marker.glyph, style=marker.style)
    node.append(row.path)
    node.append(
        marker.note.format(
            owner=row.overridden_by or 'root',
            from_=row.promoted_from,
        ),
        style=marker.note_styled,
    )
    return SummaryNode(label=node)


def _applied_stats_parts(stats: AppliedStats) -> list[str]:
    """Markup parts for the applied-counts suffix, omitting zero counts."""
    stat_items = [
        (stats.written, '[green]{n} written[/green]'),
        (stats.unchanged, '[dim]{n} unchanged[/dim]'),
        (stats.deleted, '[dim red]{n} deleted[/dim red]'),
        (stats.drift, '[red]{n} drift[/red]'),
        (stats.skipped, '[yellow]{n} skipped[/yellow]'),
        (stats.symlinks, '[blue]{n} symlinks[/blue]'),
        (stats.copies, '[yellow]{n} copies[/yellow]'),
    ]
    return [fmt.format(n=n) for n, fmt in stat_items if n]


def _append_stats(label: Text, stats: AppliedStats | PendingStats) -> None:
    """Append a provider branch's count suffix to *label* in place."""
    if isinstance(stats, AppliedStats):
        parts = _applied_stats_parts(stats)
        if parts:
            stat_suffix(label, parts)
        return
    copy_note = f', {stats.copies} copies' if stats.copies else ''
    if stats.not_applied:
        label.append(
            f'  [{stats.applied} applied, {stats.not_applied} not applied{copy_note}]',
            style='dim yellow',
        )
    else:
        noun = 'file' if stats.applied == 1 else 'files'
        label.append(f'  [{stats.applied} {noun}{copy_note}]', style='dim')


def render_provider_branch(branch: ProviderBranch) -> SummaryNode:
    """Draw one provider branch: bold alias, version, stats, child rows."""
    label = Text()
    label.append(branch.alias, style=_link_style(branch.link, prefix='bold'))
    if branch.version is not None:
        label.append(f'@{branch.version}', style='dim')
    if branch.stats is not None:
        _append_stats(label, branch.stats)
    children = []
    for row in branch.rows:
        if isinstance(row, FileRow):
            children.append(render_file_row(row))
        elif isinstance(row, SymlinkRow):
            children.append(render_symlink_row(row))
        else:
            children.append(render_copy_row(row))
    return SummaryNode(label=label, children=children)


def render_session_group(group: SessionGroup) -> SummaryNode:
    """Draw one role group: bold title, provider branches, promoted subgroup."""
    children = [render_provider_branch(branch) for branch in group.branches]
    if group.promoted:
        children.append(
            SummaryNode(
                label=Text('Promoted', style='bold'),
                children=[render_promoted_row(row) for row in group.promoted],
            ),
        )
    return SummaryNode(label=Text(group.title, style='bold'), children=children)


def render_command_row(row: CommandRow) -> SummaryNode:
    """Draw one post-process command row: marker, raw command, outcome."""
    marker = marker_for(row.state)
    node = Text()
    node.append(marker.glyph, style=marker.style)
    node.append(row.raw)
    if row.state is CommandState.OK:
        node.append(f'  ok ({format_duration(row.duration_ms)})', style='dim')
    elif row.state is CommandState.NOT_RUN:
        node.append('  not run (previous command failed)', style='dim yellow')
    else:
        note = row.error or f'exit {row.returncode}'
        node.append(f'  FAILED {note}', style='red')
    return SummaryNode(label=node)


def _group_suffix(label: str, ok: int, failed: int, not_run: int) -> Text:
    """Compose a post-process group label with its ok/failed/not-run counts."""
    text = Text(label, style='bold')
    parts = [
        f'[green]{ok} ok[/green]',
        f'[red]{failed} failed[/red]',
        f'[yellow]{not_run} not run[/yellow]',
    ]
    parts = [
        part
        for count, part in zip(
            (ok, failed, not_run),
            parts,
            strict=False,
        )
        if count
    ]
    if parts:
        stat_suffix(text, parts)
    return text


def render_post_process_group(group: PostProcessGroup) -> SummaryNode:
    """Draw one post-process group: counted label, report link, command rows."""
    label = _group_suffix(group.label, group.ok, group.failed, group.not_run)
    if group.link is not None:
        details_link(label, group.link)
    children = [render_command_row(row) for row in group.commands]
    children.extend(render_post_process_group(sub) for sub in group.subgroups)
    return SummaryNode(label=label, children=children)


def render_session_groups(groups: Sequence[SessionGroup]) -> list[SummaryNode]:
    """Render every session group into nodes, in order.

    Shared by every summary built from `SessionGroup` rows — the apply
    summary and the link/copy summaries alike.
    """
    return [render_session_group(group) for group in groups]


def render_post_process_summary(
    groups: Sequence[PostProcessGroup],
) -> list[SummaryNode]:
    """Render every post-process group into nodes, in order."""
    return [render_post_process_group(group) for group in groups]
