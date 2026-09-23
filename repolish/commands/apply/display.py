"""CLI-facing summary output: banners, tables, and tree composition.

The summary trees live in their own packages:
`repolish.summaries` derives typed rows from the finished session,
`repolish.reporting` renders them. This module keeps the console
I/O repolish owns directly: the startup banner, pre-apply file tables,
member-run notes and errors, and the composition that prints the run's
summary trees and footer.
"""

from collections.abc import Sequence
from pathlib import Path

from rich.table import Table

from repolish.commands.apply.options import ResolvedSession
from repolish.config import ProviderSymlink
from repolish.console import console
from repolish.phases import write_phase_timings
from repolish.providers.models import SessionBundle
from repolish.reporting import (
    SummaryNode,
    print_completed_footer,
    print_summary_trees,
)
from repolish.reporting.leaves import (
    MODE_STYLES,
    render_apply_summary,
    render_post_process_summary,
)
from repolish.summaries import (
    apply_summary_rows,
    post_process_rows,
    session_label,
)
from repolish.version import __version__


def print_startup() -> None:
    """Print the repolish startup banner."""
    console.print(f'[bold cyan]repolish[/bold cyan] [dim]v{__version__}[/dim]')


def note_running_from_member(config_dir: Path, root: Path, rel: Path) -> None:
    """Print an informational note when `apply` runs standalone from a member directory.

    Running from a member is allowed — the member's own providers and templates
    apply correctly.  The root session is simply skipped, so root-managed files
    are not updated in this pass.

    Args:
        config_dir: The current working directory (member path).
        root: The detected monorepo root directory.
        rel: The member path relative to the monorepo root.
    """
    msg = (
        '[dim]note:[/] running standalone from member directory (root pass skipped)\n'
        f'  [dim]{config_dir}[/] is a member of [dim]{root}[/]\n'
        f'  for a full monorepo run: [bold]repolish apply --member {rel}[/] from the root'
    )
    console.print(msg)


def error_unknown_member(member: str, valid_names: list[str]) -> None:
    """Display an error when `--member` does not match any known member.

    Args:
        member: The member identifier passed on the command line.
        valid_names: The list of known member names that can be used instead.
    """
    valid_names_str = ', '.join(f'[bold]{n}[/bold]' for n in valid_names)
    msg = (
        f'[bold red]error:[/] unknown member [bold]{member!r}[/]\n\n'
        f'[bold yellow]hint:[/] valid members: {valid_names_str}'
    )
    console.print(msg)


def _build_provider_table(
    owner: str,
    records: list,
    owner_symlinks: list[ProviderSymlink],
) -> Table:
    """Build a Rich Table for one provider showing files and symlinks."""
    total = len(records) + len(owner_symlinks)
    title = f'{owner} ({total} file{"s" if total != 1 else ""})'
    table = Table(title=title, show_header=True, header_style='bold')
    table.add_column('Mode', style='dim', no_wrap=True)
    table.add_column('Path')
    table.add_column('Source', style='dim')
    for record in records:
        mode_val = record.mode.value
        style = MODE_STYLES.get(mode_val, '')
        source = record.source if record.source and record.source != record.path else ''
        if not source and record.overlay_dir:
            source = f'{record.overlay_dir}/'
        table.add_row(f'[{style}]{mode_val}[/{style}]', record.path, source)
    for sl in owner_symlinks:
        table.add_row('[blue]symlink[/blue]', str(sl.target), str(sl.source))
    return table


def print_files_summary(
    providers: SessionBundle,
    symlinks: dict[str, list[ProviderSymlink]] | None = None,
) -> None:
    """Print one Rich table per provider alias showing mode and path for each file."""
    by_owner: dict[str, list] = {}
    for record in providers.file_records:
        by_owner.setdefault(record.owner, []).append(record)

    _syms = symlinks if symlinks is not None else {}
    all_owners = list(by_owner.keys())
    for alias in _syms:
        if alias not in all_owners:
            all_owners.append(alias)

    for owner in all_owners:
        console.print(
            _build_provider_table(
                owner,
                by_owner.get(owner, []),
                _syms.get(owner, []),
            ),
        )


def apply_summary_nodes(
    sessions: Sequence[ResolvedSession],
) -> list[SummaryNode]:
    """Render the apply summary tree nodes for every session."""
    return render_apply_summary(apply_summary_rows(sessions))


def print_run_summary(sessions: Sequence[ResolvedSession]) -> None:
    """Print the run's summary trees: post-process first, apply summary last.

    Sessions that ran no post-process commands contribute nothing, so the
    post-process tree is simply absent for runs without a ``post_process``
    config.
    """
    print_summary_trees(
        [
            (
                'post-process summary',
                render_post_process_summary(post_process_rows(sessions)),
            ),
            ('apply summary', apply_summary_nodes(sessions)),
        ],
    )


def print_run_footer(
    sessions: Sequence[ResolvedSession],
    total_ms: float,
    config_dir: Path,
) -> None:
    """Write the phase-timings JSON and print the `completed in ...` footer.

    One file per command at *config_dir* (`.repolish/_/phase-timings.json`),
    holding each session's phase durations; the footer links to it. Timings
    live only here — the post-process report no longer repeats them.
    """
    timings_path = write_phase_timings(
        config_dir / '.repolish' / '_' / 'phase-timings.json',
        total_ms,
        [(session_label(session), session.phase_timer) for session in sessions],
    )
    print_completed_footer(int(total_ms), timings_path)
