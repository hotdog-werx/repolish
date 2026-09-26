from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

from repolish.commands.apply import ApplyOptions, resolve_session
from repolish.console import console
from repolish.reporting import print_command_timings, print_summary_trees
from repolish.reporting.leaves import render_insertion_catalog
from repolish.summaries import insertion_function_rows, session_label

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ListInsertionsOptions:
    """Options for listing available insertion functions."""

    config_path: Path
    provider: str | None = None
    function: str | None = None


def command(options: ListInsertionsOptions) -> int:
    """List insertion functions available from configured providers.

    The footer reuses the session's own `PhaseTimer` (resolution is the
    whole run).
    """
    started = perf_counter()
    session = resolve_session(ApplyOptions(config_path=options.config_path))
    groups = insertion_function_rows(
        session,
        provider=options.provider,
        function=options.function,
    )
    if not groups:
        console.print('No insertion functions found for the requested filters.')
    else:
        functions = sum(len(group.functions) for group in groups)
        print_summary_trees(
            [
                (
                    f'available insertion functions ({len(groups)} providers, {functions} functions)',
                    render_insertion_catalog(groups),
                ),
            ],
        )
    print_command_timings(
        'list-insertions',
        (perf_counter() - started) * 1000,
        [(session_label(session), session.phase_timer)],
        options.config_path.resolve().parent,
    )
    return 0
