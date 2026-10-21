"""Docs insertion functions: tables derived from product code, end to end.

Unit tests pin each renderer against the registry it derives from; the
lane e2e runs the real `docs` fast lane (the same shape LocalProvider
declares) against fixture docs files, asserting the blocks fill, stay
idempotent under `--check`, and fail the check when corrupted.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import textwrap
from typing import TYPE_CHECKING, Any

import pytest
from local_provider.docs_insertions import (
    exit_codes,
    facet_hooks,
    hook_skip_semantics,
    summary_markers,
)

from repolish.providers.models import HOOK_SKIP_SEMANTICS
from repolish.providers.models.facet import ProviderFacet
from repolish.summaries.rows import STATE_ENUMS
from repolish.testing import apply_fast_lane

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
# Lane e2e: the `docs` lane shape LocalProvider declares, against fixture docs
# ---------------------------------------------------------------------------

_LANE_PROVIDER = """\
    from repolish import BaseContext, BaseInputs, FastLaneSpec, Provider
    from local_provider.docs_insertions import DOCS_INSERTIONS

    class Ctx(BaseContext):
        pass

    class P(Provider[Ctx, BaseInputs]):
        def create_context(self):
            return Ctx()

        def create_fast_lanes(self, repolish):
            return {'docs': FastLaneSpec(file_insertions=DOCS_INSERTIONS)}
    """

_BLOCKS: dict[str, list[str]] = {
    'docs/reference/summary-trees.md': [
        '<!-- repolish:on:marker-rows summary-markers rows -->',
        '<!-- repolish:on:validator-lines summary-markers validator-lines -->',
    ],
    'docs/reference/apply.md': [
        '<!-- repolish:on:exit-codes exit-codes apply -->',
    ],
    'docs/reference/lint.md': [
        '<!-- repolish:on:exit-codes exit-codes lint -->',
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


def _make_lane_provider(base: Path) -> type[Provider[Any, Any]]:
    """Write the docs-lane fixture provider package and import its class."""
    provider_root = base / 'pkg' / 'resources' / 'templates'
    (provider_root / 'repolish').mkdir(parents=True)
    (provider_root / 'repolish.py').write_text(
        textwrap.dedent(_LANE_PROVIDER),
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


def test_docs_lane_fills_every_block_and_check_stays_clean(
    tmp_path: Path,
) -> None:
    provider_cls = _make_lane_provider(tmp_path)
    project = tmp_path / 'project'
    _make_project(project)

    result = apply_fast_lane(provider_cls, project, 'docs', alias='local')

    assert result.exit_code == 0
    trees = (project / 'docs/reference/summary-trees.md').read_text(
        encoding='utf-8',
    )
    assert '| `✓` | `written` |' in trees
    apply_doc = (project / 'docs/reference/apply.md').read_text(
        encoding='utf-8',
    )
    assert '| `2` |' in apply_doc
    providers_doc = (project / 'docs/provider-development/providers.md').read_text(
        encoding='utf-8',
    )
    assert '| `create_anchors` |' in providers_doc

    clean = apply_fast_lane(
        provider_cls,
        project,
        'docs',
        alias='local',
        check_only=True,
    )
    assert clean.exit_code == 0


def test_docs_lane_check_flags_a_corrupted_block(tmp_path: Path) -> None:
    provider_cls = _make_lane_provider(tmp_path)
    project = tmp_path / 'project'
    _make_project(project)
    applied = apply_fast_lane(provider_cls, project, 'docs', alias='local')
    assert applied.exit_code == 0

    target = project / 'docs/reference/apply.md'
    target.write_text(
        target.read_text(encoding='utf-8').replace('| `2` |', '| `3` |'),
        encoding='utf-8',
    )
    drift = apply_fast_lane(
        provider_cls,
        project,
        'docs',
        alias='local',
        check_only=True,
    )
    assert drift.exit_code == 2
