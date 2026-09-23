from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from repolish.commands.apply import ApplyOptions, resolve_session
from repolish.console import console
from repolish.reporting import print_summary_trees
from repolish.reporting.leaves import render_insertion_catalog
from repolish.summaries import insertion_function_rows

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ListInsertionsOptions:
    """Options for listing available insertion functions."""

    config_path: Path
    provider: str | None = None
    function: str | None = None


def command(options: ListInsertionsOptions) -> int:
    """List insertion functions available from configured providers."""
    session = resolve_session(ApplyOptions(config_path=options.config_path))
    groups = insertion_function_rows(
        session,
        provider=options.provider,
        function=options.function,
    )
    if not groups:
        console.print('No insertion functions found for the requested filters.')
        return 0

    functions = sum(len(group.functions) for group in groups)
    print_summary_trees(
        [
            (
                f'available insertion functions ({len(groups)} providers, {functions} functions)',
                render_insertion_catalog(groups),
            ),
        ],
    )
    return 0
