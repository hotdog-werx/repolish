import json
from pathlib import Path
from textwrap import dedent

import pytest

from repolish.cli.main import app
from repolish.cli.testing import CliRunner

runner = CliRunner()


def test_list_insertions_shows_provider_functions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider_dir = tmp_path / 'p'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        dedent(
            """\
            from repolish import BaseContext, BaseInputs, Provider


            class Ctx(BaseContext):
                pass


            class P(Provider[Ctx, BaseInputs]):
                def create_context(self):
                    return Ctx()

                def create_file_insertions(self, context):
                    return ['README.md']

                def create_insertion_registry(self, context):
                    def generate_uv_sources(mode: str):
                        \"\"\"Generate uv source block for one mode.\"\"\"
                        return f'sources={mode}'

                    return {'generate-uv-sources': generate_uv_sources}
            """,
        ),
        encoding='utf-8',
    )

    (tmp_path / 'README.md').write_text(
        '<!-- repolish:on:uv generate-uv-sources local -->\n<!-- repolish:off:uv -->\n',
        encoding='utf-8',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}, indent=4),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ['list-insertions'])

    assert result.exit_code == 0
    assert 'available insertion functions' in result.output
    assert 'p' in result.output
    assert 'generate-uv-sources' in result.output
    assert 'Generate uv source block for one mode.' in result.output
    # The per-file allowlist is labeled as the developer-marker scope;
    # template zones get the whole registry.
    assert 'files (repolish:on markers)' in result.output
    assert 'README.md' in result.output
    assert 'template zones may call any listed function' in result.output


def test_list_insertions_filters_by_provider_and_function(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider_dir = tmp_path / 'p'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        dedent(
            """\
            from repolish import BaseContext, BaseInputs, Provider


            class Ctx(BaseContext):
                pass


            class P(Provider[Ctx, BaseInputs]):
                def create_context(self):
                    return Ctx()

                def create_file_insertions(self, context):
                    return {'README.md': {'render-a': lambda: 'a', 'render-b': lambda: 'b'}}
            """,
        ),
        encoding='utf-8',
    )

    (tmp_path / 'README.md').write_text(
        '<!-- repolish:on:one render-a -->\n<!-- repolish:off:one -->\n',
        encoding='utf-8',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}, indent=4),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ['list-insertions', '-p', 'p', '-f', 'render-a'],
    )

    assert result.exit_code == 0
    assert 'render-a' in result.output
    assert 'render-b' not in result.output


def test_list_insertions_shows_message_when_no_functions_match_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider_dir = tmp_path / 'p'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        dedent(
            """\
            from repolish import BaseContext, BaseInputs, Provider


            class Ctx(BaseContext):
                pass


            class P(Provider[Ctx, BaseInputs]):
                def create_context(self):
                    return Ctx()

                def create_file_insertions(self, context):
                    return {'README.md': {'render-a': lambda: 'a'}}
            """,
        ),
        encoding='utf-8',
    )

    (tmp_path / 'README.md').write_text(
        '<!-- repolish:on:one render-a -->\n<!-- repolish:off:one -->\n',
        encoding='utf-8',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}, indent=4),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ['list-insertions', '-f', 'nonexistent-function'],
    )

    assert result.exit_code == 0
    assert 'No insertion functions found for the requested filters.' in result.output


def test_list_insertions_filter_does_not_match_other_provider_qualified_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Filtering by unqualified name doesn't match other-provider-qualified keys."""
    provider_dir = tmp_path / 'p'
    provider_dir.mkdir()
    (provider_dir / 'repolish.py').write_text(
        dedent(
            """\
            from repolish import BaseContext, BaseInputs, Provider


            class Ctx(BaseContext):
                pass


            class P(Provider[Ctx, BaseInputs]):
                def create_context(self):
                    return Ctx()

                def create_file_insertions(self, context):
                    return {
                        'README.md': {
                            'unknown:render-a': lambda: 'a',
                            'render-b': lambda: 'b',
                        },
                    }
            """,
        ),
        encoding='utf-8',
    )

    (tmp_path / 'README.md').write_text(
        '<!-- repolish:on:one render-b -->\n<!-- repolish:off:one -->\n',
        encoding='utf-8',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}, indent=4),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ['list-insertions', '-f', 'render-a'])

    assert result.exit_code == 0
    assert 'No insertion functions found for the requested filters.' in result.output
