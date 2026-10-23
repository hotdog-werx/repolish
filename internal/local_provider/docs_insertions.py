"""Docs insertion functions: data tables derived from repolish code.

Each function renders a markdown table from a registry that lives in the
product package next to the behavior it documents: `MARKERS` descriptions,
the exit-code contracts, `HOOK_SKIP_SEMANTICS`, the `ProviderFacet`
docstrings, and the CLI parameter models. The docs data tables cannot drift
from the implementation, because `workspace:repolish:check` re-renders every
block in CI. `DOCS_INSERTION_FILES` is the allowlist `create_file_insertions`
returns; `DOCS_INSERTION_REGISTRY` is the shared function registry
`create_insertion_registry` hands back for those files.
"""

from collections.abc import Callable
from enum import Enum
from typing import get_args, get_origin

from cyclopts import Parameter as CycloptsParameter
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from repolish.cli.apply import ApplyParams, apply
from repolish.cli.link import LinkParams, link
from repolish.cli.lint import LintParams, lint
from repolish.cli.list_insertions import ListInsertionsParams, list_insertions
from repolish.cli.preview import PreviewParams, preview
from repolish.cli.scaffold import ScaffoldParams, scaffold
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


_CLI_PARAMS: dict[str, type[BaseModel]] = {
    'apply': ApplyParams,
    'link': LinkParams,
    'lint': LintParams,
    'preview': PreviewParams,
    'scaffold': ScaffoldParams,
    'list-insertions': ListInsertionsParams,
}
"""Cyclopts parameter models by command name, for cli_options."""

_CLI_COMMAND_FUNCS: dict[str, Callable[..., object]] = {
    'apply': apply,
    'link': link,
    'lint': lint,
    'preview': preview,
    'scaffold': scaffold,
    'list-insertions': list_insertions,
}
"""CLI entry functions by command name, for cli_commands.

Keyed identically to _CLI_PARAMS (a test pins the two key sets together):
every command that has an argument-table page also lands in the command
index, so a newly registered command is missing from the docs until it is
added to both."""

_VALUE_PLACEHOLDERS: dict[type, str] = {
    str: 'VALUE',
}
"""Value placeholder by parameter type; other types use the type name."""


def _cyclopts_parameter_names(field: FieldInfo) -> tuple[str, ...]:
    """The names a field binds by, from the cyclopts Parameter it declares."""
    for meta in field.metadata:
        if isinstance(meta, CycloptsParameter) and meta.name:
            return tuple(meta.name)
    msg = f'no named cyclopts Parameter on field with default {field.default!r}'
    raise ValueError(msg)


def _value_placeholder(field: FieldInfo) -> str:
    """The value suffix a flag takes, empty for booleans and positionals."""
    annotation = field.annotation
    if get_origin(annotation) is not None:
        args = [a for a in get_args(annotation) if a is not type(None)]
        annotation = args[0] if args else annotation
    if annotation is bool:
        return ''
    placeholder = _VALUE_PLACEHOLDERS.get(annotation)
    if placeholder is None:
        placeholder = getattr(annotation, '__name__', str(annotation)).upper()
    return f' {placeholder}'


def _argument_names(field: FieldInfo) -> str:
    """The names a parameter binds by, flags with their value placeholder."""
    names = _cyclopts_parameter_names(field)
    if not names[0].startswith('-'):
        return ', '.join(f'`{name}`' for name in names)
    placeholder = _value_placeholder(field)
    return ', '.join(f'`{name}{placeholder}`' for name in names)


def _default_cell(field: FieldInfo) -> str:
    """The default as the docs show it: `-` when the argument is required."""
    if field.is_required():
        return '`-`'
    return f'`{field.default}`'


def cli_options(command: str) -> str:
    """Argument table; `command` picks the cyclopts parameter model."""
    try:
        params_cls = _CLI_PARAMS[command]
    except KeyError:
        allowed = ', '.join(sorted(_CLI_PARAMS))
        msg = f'unknown command {command!r}; expected one of: {allowed}'
        raise ValueError(msg) from None
    rows = tuple(
        (
            _argument_names(field),
            _default_cell(field),
            _cell(field.description or ''),
        )
        for field in params_cls.model_fields.values()
    )
    return _table(('Argument', 'Default', 'Description'), rows)


def cli_commands() -> str:
    """Command index for the CLI landing page, from the entry functions.

    One row per registered command: the page link is `<command>.md` beside
    the docs file this table lives in, and the description is the
    function's docstring first line. A command registered on the app but
    missing here renders nothing and fails the pin test instead.
    """
    rows = tuple(
        (
            f'[`{name}`]({name}.md)',
            _cell((func.__doc__ or '').strip().split('\n')[0]),
        )
        for name, func in sorted(_CLI_COMMAND_FUNCS.items())
    )
    return _table(('Command', 'Description'), rows)


DOCS_INSERTION_FILES: tuple[str, ...] = (
    'docs/reference/summary-trees.md',
    'docs/reference/index.md',
    'docs/reference/apply.md',
    'docs/reference/link.md',
    'docs/reference/lint.md',
    'docs/reference/list-insertions.md',
    'docs/reference/preview.md',
    'docs/reference/scaffold.md',
    'docs/provider-development/facets.md',
    'docs/provider-development/providers.md',
)
"""Docs files that may carry this provider's insertion blocks."""


DOCS_INSERTION_REGISTRY: dict[str, Callable[..., str]] = {
    'summary-markers': summary_markers,
    'exit-codes': exit_codes,
    'cli-options': cli_options,
    'cli-commands': cli_commands,
    'facet-hooks': facet_hooks,
    'hook-skip-semantics': hook_skip_semantics,
}
"""The shared insertion functions, keyed by marker function name.

Every listed file resolves against this whole registry; the marker in the
file picks the function, so a new block needs no provider change."""
