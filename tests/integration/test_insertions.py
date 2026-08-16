"""Integration tests for provider-driven insertion blocks in non-owned files."""

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


def test_provider_insertion_updates_non_owned_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider can fill a reserved block in a file it does not own via mappings."""
    _write(
        tmp_path / 'README.md',
        """\
        This is the current year

        <!-- repolish:on:year display-year -->
        <!-- repolish:off:year -->
        """,
    )
    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_year(*, context, tag, args):
                    assert tag == 'year'
                    assert args == ()
                    assert context.repolish.workspace.mode in {'standalone', 'root', 'member'}
                    return '2026'

                return {'README.md': {'display-year': display_year}}
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])
    expected = dedent(
        """\
        This is the current year

        <!-- repolish:on:year display-year -->
        2026
        <!-- repolish:off:year -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert '◌ README.md  no file in stage' in result.output
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output

    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.json'
    assert report.exists()
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['file'] == 'README.md'
    assert data['source_provider']
    assert data['total_blocks'] == 1
    assert data['failed_blocks'] == 0
    assert data['functions'] == ['display-year']


def test_provider_insertion_invalid_function_name_reports_failed_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing insertion functions are reported as failed in output and report artifacts."""
    _write(
        tmp_path / 'README.md',
        """\
        Mixed insertion blocks

        <!-- repolish:on:ok display-year -->
        <!-- repolish:off:ok -->

        <!-- repolish:on:bad missing-function -->
        <!-- repolish:off:bad -->
        """,
    )
    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_year(*, args):
                    return '2026'

                return {'README.md': {'display-year': display_year}}
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    rendered = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert '<!-- repolish:on:ok display-year -->\n2026\n<!-- repolish:off:ok -->' in rendered
    assert '<!-- repolish:on:bad missing-function -->' in rendered
    assert '<!-- repolish:off:bad -->' in rendered
    assert 'insertions: ✗ failed (1 ok, 1 failed)' in result.output

    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.json'
    assert report.exists()
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['file'] == 'README.md'
    assert data['total_blocks'] == 2
    assert data['failed_blocks'] == 1
    assert data['functions'] == ['display-year', 'missing-function']
    assert data['diagnostics']
    assert "No renderer registered for function 'missing-function'." in data['diagnostics'][0]['message']


def test_provider_insertion_uses_function_args_across_three_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single insertion function can render three blocks based on args."""
    _write(
        tmp_path / 'README.md',
        """\
        Controlled sections

        <!-- repolish:on:one display-mode on -->
        <!-- repolish:off:one -->

        <!-- repolish:on:two display-mode off -->
        <!-- repolish:off:two -->

        <!-- repolish:on:three display-mode maybe -->
        <!-- repolish:off:three -->
        """,
    )
    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_mode(*, args):
                    flag = args[0]
                    if flag == 'on':
                        return 'VISIBLE'
                    if flag == 'off':
                        return 'HIDDEN'
                    return f'UNKNOWN:{flag}'

                return {'README.md': {'display-mode': display_mode}}
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])
    expected = dedent(
        """\
        Controlled sections

        <!-- repolish:on:one display-mode on -->
        VISIBLE
        <!-- repolish:off:one -->

        <!-- repolish:on:two display-mode off -->
        HIDDEN
        <!-- repolish:off:two -->

        <!-- repolish:on:three display-mode maybe -->
        UNKNOWN:maybe
        <!-- repolish:off:three -->
        """,
    )
    assert '3 ok, 0 failed' in result.output
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected


def test_provider_insertion_resolves_two_functions_for_same_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two different registered functions can target the same file and render from args."""
    _write(
        tmp_path / 'README.md',
        """\
        Function registry demo

        <!-- repolish:on:first join-parts alpha beta gamma -->
        <!-- repolish:off:first -->

        <!-- repolish:on:second join-with-dashes one two three -->
        <!-- repolish:off:second -->
        """,
    )
    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def join_parts(a, b, c):
                    return ':'.join((a, b, c))

                def join_with_dashes(a, b, c):
                    return ':'.join((a, b, c))

                return {
                    'README.md': {
                        'join-parts': join_parts,
                        'join-with-dashes': join_with_dashes,
                    }
                }
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])
    expected = dedent(
        """\
        Function registry demo

        <!-- repolish:on:first join-parts alpha beta gamma -->
        alpha:beta:gamma
        <!-- repolish:off:first -->

        <!-- repolish:on:second join-with-dashes one two three -->
        one:two:three
        <!-- repolish:off:second -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert '2 ok, 0 failed' in result.output


def test_provider_insertion_resolves_same_function_name_by_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two providers can expose the same function name using provider-qualified markers."""
    _write(
        tmp_path / 'README.md',
        """\
        Provider-qualified lookup

        <!-- repolish:on:one alpha:display-year -->
        <!-- repolish:off:one -->

        <!-- repolish:on:two beta:display-year -->
        <!-- repolish:off:two -->

        <!-- repolish:on:three display-year -->
        <!-- repolish:off:three -->
        """,
    )
    _write(
        tmp_path / 'alpha' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_year(*, args):
                    return '2026:alpha'

                return {'README.md': {'display-year': display_year}}
        """,
    )
    _write(
        tmp_path / 'beta' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_year(*, args):
                    return '2026:beta'

                return {'README.md': {'display-year': display_year}}
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'alpha': {
                        'provider_root': './alpha',
                    },
                    'beta': {
                        'provider_root': './beta',
                    },
                },
                'providers_order': ['alpha', 'beta'],
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])
    expected = dedent(
        """\
        Provider-qualified lookup

        <!-- repolish:on:one alpha:display-year -->
        2026:alpha
        <!-- repolish:off:one -->

        <!-- repolish:on:two beta:display-year -->
        2026:beta
        <!-- repolish:off:two -->

        <!-- repolish:on:three display-year -->
        2026:alpha
        <!-- repolish:off:three -->
        """,
    )
    assert 'no file in stage' in result.output
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected


def test_provider_insertion_check_passes_when_file_is_in_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`apply --check` succeeds when insertion output is already up to date."""
    _write(
        tmp_path / 'README.md',
        """\
        This is the current year

        <!-- repolish:on:year display-year -->
        2026
        <!-- repolish:off:year -->
        """,
    )
    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_year(*, context, tag, args):
                    return '2026'

                return {'README.md': {'display-year': display_year}}
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--check'], exit_code=0)


def test_provider_insertion_check_fails_when_file_drifted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`apply --check` reports drift when insertion-managed content is stale."""
    _write(
        tmp_path / 'README.md',
        """\
        This is the current year

        <!-- repolish:on:year display-year -->
        1999
        <!-- repolish:off:year -->
        """,
    )
    _write(
        tmp_path / 'p' / 'repolish.py',
        """\
        from repolish import BaseContext, BaseInputs, Provider


        class Ctx(BaseContext):
            pass


        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_insertions(self, context):
                def display_year(*, context, tag, args):
                    return '2026'

                return {'README.md': {'display-year': display_year}}
        """,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply', '--check'], exit_code=2)
    assert 'README.md' in result.output
    assert 'run `repolish apply` to apply changes' in result.output
