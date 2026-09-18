"""The summary-tree contract: nodes, status markers, and label helpers.

Producers build `SummaryNode` trees (plain data, no rich Tree knowledge);
`repolish.reporting.render` turns them into rich output. Everything a
summary can say — a status marker, a details link, a stat suffix — has a
helper here so producers never touch link styles or separators directly.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from rich.text import Text

from repolish.console import supports_hyperlinks


class Status(Enum):
    """Outcome markers with their style, keyed by display intent."""

    OK = ('✓ ', 'green')
    WARN = ('⚠ ', 'yellow')
    FAIL = ('✗ ', 'red')
    SKIP = ('✗ ', 'yellow')
    INFO = ('~ ', 'dim cyan')

    @property
    def marker(self) -> str:
        """The glyph prefix for this status, e.g. `'✓ '`."""
        return self.value[0]

    @property
    def style(self) -> str:
        """The rich style for this status's marker, e.g. `'green'`."""
        return self.value[1]


@dataclass
class SummaryNode:
    """One row of a summary tree.

    *label* is composed freely by the producer (markers, dim annotations,
    stat suffixes); *link* turns the whole label into a `file://` hyperlink
    when the terminal supports it; *children* nest beneath.
    """

    label: Text
    children: list['SummaryNode'] = field(default_factory=list)
    link: Path | None = None


def status_prefix(status: Status) -> Text:
    """Return the marker for *status* styled with its color."""
    return Text(status.marker, style=status.style)


def details_link(text: Text, path: Path) -> None:
    """Append a ` [details]` hyperlink to *path* onto *text* in place.

    No-op (not even the trailing text) when the console does not support
    hyperlinks, matching the validator and insertion report links.
    """
    if not supports_hyperlinks:
        return
    style = f'link file://{path.absolute()}'
    text.append(' [details]', style=style)


def stat_suffix(text: Text, parts: list[str]) -> None:
    """Append formatted stat *parts* to *text* separated by dim `·` dots.

    Each part is rich markup (e.g. `'[green]2 written[/green]'`); empty or
    falsy parts are skipped by the caller.
    """
    text.append('  ')
    for i, part in enumerate(parts):
        if i:
            text.append(' · ', style='dim')
        text.append_text(Text.from_markup(part))
