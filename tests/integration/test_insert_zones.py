"""End-to-end: provider-branded insertion zones through the apply pipeline.

A template declares ``repolish:insert[badges]``; the directive line vanishes
during rendering, provider functions fill the branded markers at insertion
time, and developer edits to the opening marker's args survive re-apply.
"""

from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding='utf-8')


TEMPLATE = """\
# Badges

## repolish:insert[badges] start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"
<!-- generated:badges:on repolish/repolish style=flat -->
_default badge row._
<!-- generated:badges:off -->
"""

PROVIDER_WITH_FILL = """\
from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    pass


class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_insertions(self, context):
        def badges(*args):
            return 'BADGES(' + ' '.join(args) + ')'
        return {'README.md': {'badges': badges}}
"""


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    _write(tmp_path / 'p' / 'repolish.py', provider)
    _write(tmp_path / 'p' / 'repolish' / 'README.md', TEMPLATE)
    config = {'providers': {'p': {'provider_root': './p'}}}
    (tmp_path / 'repolish.yaml').write_text(json.dumps(config, indent=4), encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)


def test_zone_filled_then_args_adopted_on_reapply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(tmp_path, monkeypatch, PROVIDER_WITH_FILL)

    run_repolish(['apply'], exit_code=0)
    readme = (tmp_path / 'README.md').read_text(encoding='utf-8')
    # Directive stripped; default replaced by the zone function's output.
    assert 'repolish:insert' not in readme
    expected = dedent(
        """\
        # Badges

        <!-- generated:badges:on repolish/repolish style=flat -->
        BADGES(repolish/repolish style=flat)
        <!-- generated:badges:off -->
        """,
    )
    assert readme == expected

    # Developer tunes the opening marker's args; the body re-fills from them.
    (tmp_path / 'README.md').write_text(
        readme.replace(
            '<!-- generated:badges:on repolish/repolish style=flat -->',
            '<!-- generated:badges:on acme/widgets style=social -->',
        ),
        encoding='utf-8',
    )
    run_repolish(['apply'], exit_code=0)
    readme = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'BADGES(acme/widgets style=social)' in readme
    assert '<!-- generated:badges:on acme/widgets style=social -->' in readme

    # …and the steady state is check-clean.
    run_repolish(['apply', '--check'], exit_code=0)


def test_zone_without_renderer_keeps_template_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zone the provider never fills must ship its default, never fail."""
    _setup(
        tmp_path,
        monkeypatch,
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()
        """,
    )

    run_repolish(['apply'], exit_code=0)
    readme = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'repolish:insert' not in readme
    assert '_default badge row._' in readme
    assert '<!-- generated:badges:on repolish/repolish style=flat -->' in readme
