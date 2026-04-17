"""Integration tests for config-level anchor overrides.

Scenarios covered:
- Provider-supplied anchors render into templates
- Config-level anchors override provider-supplied anchors
- Config-level anchors add new anchors not present in provider
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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _make_anchor_provider(
    directory: Path,
    *,
    anchors: dict[str, str],
    template_content: str,
) -> None:
    """Create a minimal provider that returns anchors and a single template."""
    _write(directory / 'repolish' / 'managed.txt', template_content)
    anchors_repr = repr(anchors)
    _write(
        directory / 'repolish.py',
        f"""\
        from repolish import BaseContext, Provider, BaseInputs

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_anchors(self, ctx):
                return {anchors_repr}
        """,
    )


@dataclass
class TCase:
    name: str
    provider_anchors: dict[str, str]
    config_anchors: dict[str, str] | None
    template: str
    expected: str


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='provider_anchors_rendered',
            provider_anchors={'greeting': 'hello from provider'},
            config_anchors=None,
            template=('before\n# repolish-start[greeting]\nplaceholder\n# repolish-end[greeting]\nafter\n'),
            expected='before\nhello from provider\nafter\n',
        ),
        TCase(
            name='config_overrides_provider_anchor',
            provider_anchors={'greeting': 'hello from provider'},
            config_anchors={'greeting': 'hello from config'},
            template=('before\n# repolish-start[greeting]\nplaceholder\n# repolish-end[greeting]\nafter\n'),
            expected='before\nhello from config\nafter\n',
        ),
        TCase(
            name='config_adds_new_anchor',
            provider_anchors={'greeting': 'hello'},
            config_anchors={'extra': 'bonus content'},
            template=(
                '# repolish-start[greeting]\n'
                'placeholder\n'
                '# repolish-end[greeting]\n'
                '---\n'
                '# repolish-start[extra]\n'
                'placeholder\n'
                '# repolish-end[extra]\n'
            ),
            expected='\nhello\n---\nbonus content\n',
        ),
    ],
    ids=lambda c: c.name,
)
def test_anchor_override(
    case: TCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_anchor_provider(
        tmp_path / 'p',
        anchors=case.provider_anchors,
        template_content=case.template,
    )

    provider_config: dict[str, object] = {'provider_root': './p'}
    if case.config_anchors is not None:
        provider_config['anchors'] = case.config_anchors

    config = {'providers': {'p': provider_config}}

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(config),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply'])

    result = (tmp_path / 'managed.txt').read_text(encoding='utf-8')
    assert result == case.expected
