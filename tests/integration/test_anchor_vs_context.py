"""Equivalence check: anchors vs Jinja2 context + config overrides.

The install-extras example from docs/markers/tag-blocks.md, done two ways:

1. **Anchors** — a `repolish-start`/`repolish-end` tag block filled by
   `create_anchors()`, overridden project-side via `overrides.anchors`.
2. **Context** — a plain Jinja ``{{ install_extras }}`` variable filled by
   `create_context()`, overridden project-side via `overrides.context_merge`.

Both styles must produce byte-identical output for both the provider default
and the config override. If they do, anchors carry nothing that Jinja context
plus the existing config context-override mechanism can't already express —
the open question for v2 (see the "Anchors in v2?" note in the tag-blocks
docs).
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

TAB = '\t'

TEMPLATE_ANCHORS = f"""\
.PHONY: install
install:
## repolish-start[install-extras]
{TAB}pip install -e ".[dev]"
## repolish-end[install-extras]
"""

TEMPLATE_CONTEXT = """\
.PHONY: install
install:
{{ install_extras }}
"""

EXPECTED_PROVIDER_DEFAULT = f"""\
.PHONY: install
install:
{TAB}pip install -e ".[dev,docs,gpu]"
"""

EXPECTED_CONFIG_OVERRIDE = f"""\
.PHONY: install
install:
{TAB}pip install -e ".[minimal]"
"""

PROVIDER_ANCHORS = """\
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_anchors(self, ctx):
        return {'install-extras': '\\tpip install -e ".[dev,docs,gpu]"'}
"""

PROVIDER_CONTEXT = """\
from repolish import BaseContext, Provider, BaseInputs

class Ctx(BaseContext):
    install_extras: str = '\\tpip install -e ".[dev,docs,gpu]"'

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _make_provider(directory: Path, *, style: str) -> None:
    template = TEMPLATE_ANCHORS if style == 'anchors' else TEMPLATE_CONTEXT
    provider_code = PROVIDER_ANCHORS if style == 'anchors' else PROVIDER_CONTEXT
    _write(directory / 'repolish' / 'managed.txt', template)
    _write(directory / 'repolish.py', provider_code)


@dataclass
class TCase:
    name: str
    style: str  # 'anchors' | 'context'
    expected: str


CASES = [
    TCase('anchors_provider_default', 'anchors', EXPECTED_PROVIDER_DEFAULT),
    TCase('anchors_config_override', 'anchors', EXPECTED_CONFIG_OVERRIDE),
    TCase('context_provider_default', 'context', EXPECTED_PROVIDER_DEFAULT),
    TCase('context_config_override', 'context', EXPECTED_CONFIG_OVERRIDE),
]


@pytest.mark.parametrize('case', CASES, ids=lambda c: c.name)
def test_install_extras_anchor_vs_context(
    case: TCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_provider(tmp_path / 'p', style=case.style)

    provider_config: dict[str, object] = {'provider_root': './p'}
    # Both override mechanisms are config-level and per-provider in syntax;
    # context_merge replaces the Jinja variable, anchors replaces the block.
    override_value = f'{TAB}pip install -e ".[minimal]"'
    if 'config_override' in case.name:
        if case.style == 'anchors':
            provider_config['overrides'] = {'anchors': {'install-extras': override_value}}
        else:
            provider_config['overrides'] = {'context_merge': {'install_extras': override_value}}

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': provider_config}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    # A single shared expectation is the claim: anchors add nothing that
    # Jinja context + config overrides can't already express.
    result = (tmp_path / 'managed.txt').read_text(encoding='utf-8')
    assert result == case.expected
