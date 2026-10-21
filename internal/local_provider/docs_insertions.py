"""Docs insertion functions: data tables derived from repolish code.

Each function renders a markdown table from a registry that lives in the
product package next to the behavior it documents: `MARKERS` descriptions,
the exit-code contracts, `HOOK_SKIP_SEMANTICS`, and the `ProviderFacet`
docstrings. The docs data tables cannot drift from the implementation,
because `workspace:repolish:check` re-renders every block in CI.
`DOCS_INSERTION_FILES` is the allowlist `create_file_insertions` returns;
`DOCS_INSERTION_REGISTRY` is the shared function registry
`create_insertion_registry` hands back for those files.
"""

from collections.abc import Callable
from enum import Enum

from repolish.commands.apply.session import APPLY_EXIT_CODES
from repolish.commands.lint import LINT_EXIT_CODES
from repolish.providers.models import HOOK_SKIP_SEMANTICS
from repolish.providers.models.facet import ProviderFacet
from repolish.reporting.markers import MARKERS
from repolish.summaries.rows import (
    CommandState,
    CopyState,
    FileState,
    HookFailureState,
    PromotedState,
    ValidatorState,
)

_MARKER_HEADERS: tuple[str, ...] = ('Marker', 'State', 'Meaning')

_MARKER_SECTIONS: dict[str, tuple[tuple[str, type[Enum]], ...]] = {
    'rows': (
        ('File rows', FileState),
        ('Resource copies', CopyState),
        ('Promoted files', PromotedState),
        ('Post-process commands', CommandState),
        ('Hook failures', HookFailureState),
    ),
    'validator-lines': (('Validator lines', ValidatorState),),
}
"""Marker-table families by docs section, in tree order.

Every family renders its whole enum, so a new state member shows up in the
docs the moment it exists in code."""


def _cell(text: str) -> str:
    """One table cell: pipes escaped so no description can break the table."""
    return text.replace('|', '\\|')


def _table(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    """A markdown table, unpadded; the post-process dprint pass normalizes."""
    lines = [
        f'| {" | ".join(headers)} |',
        f'| {" | ".join("---" for _ in headers)} |',
    ]
    lines.extend(f'| {" | ".join(row)} |' for row in rows)
    return '\n'.join(lines)


def _marker_rows(enum_cls: type[Enum]) -> tuple[tuple[str, str, str], ...]:
    """One row per enum member: glyph, state value, description, verbatim."""
    return tuple(
        (
            f'`{MARKERS[state].glyph.rstrip()}`',
            f'`{state.value}`',
            _cell(MARKERS[state].description),
        )
        for state in enum_cls
    )


def summary_markers(section: str) -> str:
    """Summary-tree marker tables; `section` picks rows or validator-lines."""
    try:
        families = _MARKER_SECTIONS[section]
    except KeyError:
        allowed = ', '.join(sorted(_MARKER_SECTIONS))
        msg = f'unknown section {section!r}; expected one of: {allowed}'
        raise ValueError(msg) from None
    tables = []
    for label, enum_cls in families:
        body = _table(_MARKER_HEADERS, _marker_rows(enum_cls))
        tables.append(f'**{label}**\n\n{body}')
    return '\n\n'.join(tables)


def exit_codes(command: str) -> str:
    """Exit-code table; `command` picks apply or lint."""
    contracts = {'apply': APPLY_EXIT_CODES, 'lint': LINT_EXIT_CODES}
    try:
        codes = contracts[command]
    except KeyError:
        allowed = ', '.join(sorted(contracts))
        msg = f'unknown command {command!r}; expected one of: {allowed}'
        raise ValueError(msg) from None
    rows = tuple((f'`{code}`', _cell(meaning)) for code, meaning in sorted(codes.items()))
    return _table(('Code', 'Meaning'), rows)


def facet_hooks() -> str:
    """Provider facet hooks and their purpose, from ProviderFacet docstrings."""
    rows = tuple(
        (f'`{name}`', _cell((method.__doc__ or '').strip().split('\n')[0]))
        for name, method in vars(ProviderFacet).items()
        if not name.startswith('_') and callable(method)
    )
    return _table(('Hook', 'Purpose'), rows)


def hook_skip_semantics() -> str:
    """What a failed hook is skipped as, from HOOK_SKIP_SEMANTICS."""
    rows = tuple((f'`{hook}`', _cell(skipped_as)) for hook, skipped_as in HOOK_SKIP_SEMANTICS.items())
    return _table(('Hook', 'Skipped as'), rows)


DOCS_INSERTION_FILES: tuple[str, ...] = (
    'docs/reference/summary-trees.md',
    'docs/reference/apply.md',
    'docs/reference/lint.md',
    'docs/provider-development/facets.md',
    'docs/provider-development/providers.md',
)
"""Docs files that may carry this provider's insertion blocks."""


DOCS_INSERTION_REGISTRY: dict[str, Callable[..., str]] = {
    'summary-markers': summary_markers,
    'exit-codes': exit_codes,
    'facet-hooks': facet_hooks,
    'hook-skip-semantics': hook_skip_semantics,
}
"""The shared insertion functions, keyed by marker function name.

Every listed file resolves against this whole registry; the marker in the
file picks the function, so a new block needs no provider change."""
