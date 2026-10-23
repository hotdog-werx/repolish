"""Docs insertion functions: tables derived from product code, end to end.

Unit tests pin each renderer against the registry it derives from; the
provider e2e runs the shared-registry hook form (the same shape
LocalProvider declares: `create_file_insertions` lists the files,
`create_insertion_registry` the functions) against fixture docs files,
asserting the blocks fill, stay idempotent under `--check`, and fail the
check when corrupted.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import textwrap
from typing import TYPE_CHECKING, Annotated, Any

import pytest
from cyclopts import Parameter
from local_provider.docs_insertions import (
    _CLI_COMMAND_FUNCS,
    _CLI_PARAMS,
    DOCS_INSERTION_FILES,
    DOCS_INSERTION_REGISTRY,
    _cyclopts_parameter_names,
    _value_placeholder,
    cli_commands,
    cli_options,
    exit_codes,
    facet_hooks,
    hook_skip_semantics,
    summary_markers,
)
from pydantic import BaseModel, Field

from repolish.providers.models import HOOK_SKIP_SEMANTICS
from repolish.providers.models.facet import ProviderFacet
from repolish.summaries.rows import STATE_ENUMS
from repolish.testing import apply_provider

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from repolish.providers.models.provider import Provider

_counter = itertools.count()

_ROW_FAMILIES = (
    'FileState',
    'CopyState',
    'PromotedState',
    'CommandState',
    'HookFailureState',
)


def _load_module(path: Path) -> ModuleType:
    name = f'_docs_insertions_fixture_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _states(enum_name: str) -> tuple[str, ...]:
    """The member values of a state enum, looked up through STATE_ENUMS."""
    enum_cls = next(e for e in STATE_ENUMS if e.__name__ == enum_name)
    return tuple(m.value for m in enum_cls)


def test_summary_marker_rows_cover_every_state_member() -> None:
    """The rows table is a complete rendering, not a curated subset."""
    body = summary_markers('rows')
    for enum_name in _ROW_FAMILIES:
        for value in _states(enum_name):
            assert f'`{value}`' in body, f'{enum_name}.{value} missing from the rows table'


def test_validator_lines_cover_validator_states() -> None:
    body = summary_markers('validator-lines')
    for value in _states('ValidatorState'):
        assert f'`{value}`' in body


def test_summary_markers_states_are_verbatim_and_glyphs_trimmed() -> None:
    """State cells are enum values verbatim; glyphs carry no trailing space."""
    body = summary_markers('rows')
    assert '`active`' in body
    assert 'copy active' not in body
    assert '`✓ `' not in body
    assert '``' not in body


def test_summary_markers_rejects_unknown_section() -> None:
    with pytest.raises(ValueError, match='rows, validator-lines'):
        summary_markers('insertions')


def test_exit_codes_renders_both_contracts() -> None:
    apply_body = exit_codes('apply')
    for code in ('`0`', '`1`', '`2`'):
        assert code in apply_body
    lint_body = exit_codes('lint')
    for code in ('`0`', '`1`'):
        assert code in lint_body


def test_exit_codes_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match='apply, lint'):
        exit_codes('preview')


@pytest.mark.parametrize('command', sorted(_CLI_PARAMS))
def test_cli_options_rows_match_params_model(command: str) -> None:
    """The argument table is a complete rendering of the params model."""
    body = cli_options(command)
    for field in _CLI_PARAMS[command].model_fields.values():
        assert field.description is not None
        assert field.description in body


def test_cli_options_link_cells() -> None:
    """The link table pins its flag placeholder and positionals."""
    body = cli_options('link')
    assert '`--config PATH`, `-c PATH`' in body
    assert '`ALIAS`' in body
    assert '`MODULE`' in body


def test_cli_options_required_argument_shows_dash_default() -> None:
    """A required argument has no default value to render."""
    assert '| `PROVIDER_DIR` | `-` |' in cli_options('lint')


def test_cli_options_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match='expected one of: apply'):
        cli_options('health')


def test_cli_commands_lists_every_registered_command() -> None:
    """The command index renders one linked row per CLI entry function."""
    body = cli_commands()
    for name, func in _CLI_COMMAND_FUNCS.items():
        assert f'[`{name}`]({name}.md)' in body
        assert (func.__doc__ or '').strip().split('\n')[0] in body


def test_cli_commands_registry_matches_params_registry() -> None:
    """Every command with an argument table also lands in the command index."""
    assert set(_CLI_COMMAND_FUNCS) == set(_CLI_PARAMS)


def test_value_placeholder_unwraps_optionals() -> None:
    """An optional flag renders with the value placeholder of its inner type."""

    class Model(BaseModel):
        flag: Annotated[str | None, Parameter(name='--flag')] = Field(
            default=None,
        )

    assert _value_placeholder(Model.model_fields['flag']) == ' VALUE'


def test_cyclopts_parameter_names_raises_without_annotation() -> None:
    """A field without a named cyclopts Parameter cannot render argument names."""

    class Model(BaseModel):
        plain: str = 'x'

    with pytest.raises(ValueError, match='no named cyclopts Parameter'):
        _cyclopts_parameter_names(Model.model_fields['plain'])


def test_facet_hooks_rows_match_provider_facet() -> None:
    body = facet_hooks()
    for name, method in vars(ProviderFacet).items():
        if name.startswith('_') or not callable(method):
            continue
        assert f'`{name}`' in body
        assert (method.__doc__ or '').strip().split('\n')[0] in body


def test_hook_skip_semantics_rows_match_registry() -> None:
    body = hook_skip_semantics()
    assert body.count('\n| `') == len(HOOK_SKIP_SEMANTICS)
    for hook, skipped_as in HOOK_SKIP_SEMANTICS.items():
        assert f'`{hook}`' in body
        assert skipped_as in body


# ---------------------------------------------------------------------------
# Provider e2e: the shared-registry hook shape LocalProvider declares,
# against fixture docs files
# ---------------------------------------------------------------------------

_HOOK_PROVIDER = """\
    from repolish import BaseContext, BaseInputs, Provider
    from local_provider.docs_insertions import DOCS_INSERTION_FILES, DOCS_INSERTION_REGISTRY

    class Ctx(BaseContext):
        pass

    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()

        def create_file_insertions(self, context):
            return list(DOCS_INSERTION_FILES)

        def create_insertion_registry(self, context):
            return dict(DOCS_INSERTION_REGISTRY)
    """

_BLOCKS: dict[str, list[str]] = {
    'docs/reference/summary-trees.md': [
        '<!-- repolish:on:marker-rows summary-markers rows -->',
        '<!-- repolish:on:validator-lines summary-markers validator-lines -->',
    ],
    'docs/reference/index.md': [
        '<!-- repolish:on:commands cli-commands -->',
    ],
    'docs/reference/apply.md': [
        '<!-- repolish:on:options cli-options apply -->',
        '<!-- repolish:on:exit-codes exit-codes apply -->',
    ],
    'docs/reference/link.md': [
        '<!-- repolish:on:options cli-options link -->',
    ],
    'docs/reference/lint.md': [
        '<!-- repolish:on:options cli-options lint -->',
        '<!-- repolish:on:exit-codes exit-codes lint -->',
    ],
    'docs/reference/list-insertions.md': [
        '<!-- repolish:on:options cli-options list-insertions -->',
    ],
    'docs/reference/preview.md': [
        '<!-- repolish:on:options cli-options preview -->',
    ],
    'docs/reference/scaffold.md': [
        '<!-- repolish:on:options cli-options scaffold -->',
    ],
    'docs/provider-development/facets.md': [
        '<!-- repolish:on:facet-hooks facet-hooks -->',
    ],
    'docs/provider-development/providers.md': [
        '<!-- repolish:on:skip-semantics hook-skip-semantics -->',
    ],
}


def _block(marker: str) -> str:
    """One padded on/off pair, the way the docs files write them."""
    _, _, payload = marker.partition('repolish:on:')
    tag = payload.split()[0]
    return f'{marker}\n\n<!-- repolish:off:{tag} -->\n'


def _make_hook_provider(base: Path) -> type[Provider[Any, Any]]:
    """Write the shared-registry fixture provider package and import its class."""
    provider_root = base / 'pkg' / 'resources' / 'templates'
    (provider_root / 'repolish').mkdir(parents=True)
    (provider_root / 'repolish.py').write_text(
        textwrap.dedent(_HOOK_PROVIDER),
        encoding='utf-8',
    )
    mod = _load_module(provider_root / 'repolish.py')
    for val in vars(mod).values():
        if isinstance(val, type) and val.__module__ == mod.__name__:
            return val
    msg = 'fixture provider module exports no Provider subclass'
    raise AssertionError(msg)


def _make_project(project: Path) -> None:
    """Pre-create every docs dest with its marker blocks, bodies empty."""
    project.mkdir(parents=True, exist_ok=True)
    for dest, markers in _BLOCKS.items():
        target = project / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            '\n'.join(_block(m) for m in markers),
            encoding='utf-8',
        )


def test_docs_files_and_registry_stay_pinned() -> None:
    """The allowlist and the registry are the two halves of the declaration."""
    assert tuple(_BLOCKS) == DOCS_INSERTION_FILES
    assert set(DOCS_INSERTION_REGISTRY) == {
        'summary-markers',
        'exit-codes',
        'cli-options',
        'cli-commands',
        'facet-hooks',
        'hook-skip-semantics',
    }


def test_docs_provider_fills_every_block_and_check_stays_clean(
    tmp_path: Path,
) -> None:
    provider_cls = _make_hook_provider(tmp_path)
    project = tmp_path / 'project'
    _make_project(project)

    result = apply_provider(provider_cls, project, alias='local')

    assert result.exit_code == 0
    trees = (project / 'docs/reference/summary-trees.md').read_text(
        encoding='utf-8',
    )
    assert '| `✓` | `written` |' in trees
    apply_doc = (project / 'docs/reference/apply.md').read_text(
        encoding='utf-8',
    )
    assert '| `2` |' in apply_doc
    assert '`--fail-on-warnings`' in apply_doc
    index_doc = (project / 'docs/reference/index.md').read_text(
        encoding='utf-8',
    )
    assert '[`list-insertions`](list-insertions.md)' in index_doc
    link_doc = (project / 'docs/reference/link.md').read_text(
        encoding='utf-8',
    )
    assert '`--register-only`' in link_doc
    providers_doc = (project / 'docs/provider-development/providers.md').read_text(
        encoding='utf-8',
    )
    assert '| `create_anchors` |' in providers_doc

    clean = apply_provider(
        provider_cls,
        project,
        alias='local',
        check_only=True,
    )
    assert clean.exit_code == 0


def test_docs_provider_check_flags_a_corrupted_block(tmp_path: Path) -> None:
    provider_cls = _make_hook_provider(tmp_path)
    project = tmp_path / 'project'
    _make_project(project)
    applied = apply_provider(provider_cls, project, alias='local')
    assert applied.exit_code == 0

    target = project / 'docs/reference/apply.md'
    target.write_text(
        target.read_text(encoding='utf-8').replace('| `2` |', '| `3` |'),
        encoding='utf-8',
    )
    drift = apply_provider(
        provider_cls,
        project,
        alias='local',
        check_only=True,
    )
    assert drift.exit_code == 2
