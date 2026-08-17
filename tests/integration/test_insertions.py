"""Integration tests for provider-driven insertion blocks in non-owned files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from .conftest import fixtures, init_git_repo, run_repolish

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from repolish.cli.testing import Result


@dataclass
class TCase:
    """Test case for parametrized insertion tests."""

    name: str
    file_path: str
    file_content: str
    insertion_body: str
    expected_content: str
    extra_imports: str = ''
    extra_methods: str = ''
    expected_output_checks: tuple[str, ...] = ()
    exit_code: int | None = None
    check_mode: bool = False
    assert_fn: Callable[[Path, Result], None] | None = None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding='utf-8')


def _make_insertion_provider(
    directory: Path,
    file_insertions_body: str,
    extra_imports: str = '',
    extra_methods: str = '',
) -> None:
    """Create a minimal provider with the specified create_file_insertions body.

    Args:
        directory: The provider directory (where repolish.py will be written)
        file_insertions_body: The body of create_file_insertions method
            (the return statement with the registry dict). Use a dedented
            multi-line string starting with backslash-quote.
        extra_imports: Optional extra imports for the provider
        extra_methods: Optional extra methods like create_file_validators
    """
    body_dedented = dedent(file_insertions_body).strip()
    body_indented = '\n'.join(f'                {line}' for line in body_dedented.splitlines())

    methods_text = ''
    if extra_methods:
        methods_dedented = dedent(extra_methods).strip()
        methods_text = '\n'.join(f'    {line}' for line in methods_dedented.splitlines())

    provider_code = f"""\
from repolish import BaseContext, BaseInputs, Provider
{extra_imports}

class Ctx(BaseContext):
    pass

class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_insertions(self, context):
{body_indented}
{methods_text}
"""

    _write(directory / 'repolish.py', provider_code)


def _write_repolish_yaml(
    directory: Path,
    providers: dict[str, str],
    providers_order: list[str] | None = None,
) -> None:
    """Write a repolish.yaml with the specified provider configurations.

    Args:
        directory: The directory where repolish.yaml will be written
        providers: Dict mapping provider alias to provider_root path
        providers_order: Optional list specifying provider order
    """
    config: dict = {
        'providers': {alias: {'provider_root': root} for alias, root in providers.items()},
    }
    if providers_order:
        config['providers_order'] = providers_order

    (directory / 'repolish.yaml').write_text(
        json.dumps(config, indent=4),
        encoding='utf-8',
    )


def _assert_report_exists(tmp_path: Path, result: Result) -> None:
    """Assert that the per-provider insertion report exists and has expected fields."""
    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.p.json'
    assert report.exists()
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['file'] == 'README.md'
    assert data['source_provider']
    assert data['total_blocks'] == 1
    assert data['failed_blocks'] == 0
    assert data['functions'] == ['display-year']


def _assert_report_failed_blocks(tmp_path: Path, result: Result) -> None:
    """Assert that the report shows failed blocks."""
    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.p.json'
    assert report.exists()
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['file'] == 'README.md'
    assert data['total_blocks'] == 2
    assert data['failed_blocks'] == 1
    assert data['functions'] == ['display-year', 'missing-function']
    assert data['diagnostics']
    assert "No renderer registered for function 'missing-function'." in data['diagnostics'][0]['message']


def _assert_check_drift(tmp_path: Path, result: Result) -> None:
    """Assert that check mode reports drift."""
    assert 'README.md' in result.output
    assert 'run `repolish apply` to apply changes' in result.output


def test_provider_no_insertions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that registers empty insertions doesn't clutter the summary."""
    _write(tmp_path / 'README.md', 'no-insertions-here\n')
    _make_insertion_provider(
        tmp_path / 'p',
        "return {'README.md': {}}",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)
    # File should NOT appear in summary when there are zero insertions
    assert 'README.md' not in result.output
    assert 'insertions:' not in result.output

    # File content should be unchanged
    expected = dedent(
        """\
        no-insertions-here
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected


def test_provider_insertion_missing_file_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insertions for a non-existent file are silently skipped."""
    # Do NOT create the target file
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def display_year(*, context, tag, args):
            return '2026'
        return {'missing.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)
    # File should not appear since it doesn't exist
    assert 'missing.md' not in result.output
    assert 'no file in stage' not in result.output


def test_provider_insertion_check_missing_file_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check mode skips insertions for non-existent files."""
    # Do NOT create the target file
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def display_year(*, context, tag, args):
            return '2026'
        return {'missing.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    # Check mode should succeed (no drift for missing file)
    result = run_repolish(['apply', '--check'], exit_code=0)
    assert 'missing.md' not in result.output


def test_provider_insertion_with_hash_comment_style(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insertions work with # comment style (e.g., TOML, YAML, shell files)."""
    _write(
        tmp_path / 'ruff.toml',
        """\
        # Ruff configuration
        line-length = 88

        # repolish:on:lint add_rules
        # repolish:off:lint
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def add_rules():
            return 'select = ["E", "W"]'
        return {'ruff.toml': {'add_rules': add_rules}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected = dedent(
        """\
        # Ruff configuration
        line-length = 88

        # repolish:on:lint add_rules
        select = ["E", "W"]
        # repolish:off:lint
        """,
    )
    assert (tmp_path / 'ruff.toml').read_text(encoding='utf-8') == expected
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


def test_provider_insertion_and_validator_on_non_owned_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider can have both insertions and validators on a project-owned file."""
    _write(
        tmp_path / 'pyproject.toml',
        """\
        [project]
        name = "myproject"

        # repolish:on:deps add_deps
        # repolish:off:deps
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def add_deps():
            return 'dependencies = ["requests", "click"]'
        return {'pyproject.toml': {'add_deps': add_deps}}""",
        extra_imports='from repolish.providers.models import ValidationResult, ValidationStatus',
        extra_methods="""\
        def create_file_validators(self, context):
            def lint_toml(context, path):
                return ValidationResult(
                    status=ValidationStatus.PASS,
                    message='toml lint ok',
                    path=str(path),
                    validator_name='lint_toml',
                )
            return {'pyproject.toml': {'lint_toml': lint_toml}}
""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)
    expected = dedent(
        """\
        [project]
        name = "myproject"

        # repolish:on:deps add_deps
        dependencies = ["requests", "click"]
        # repolish:off:deps
        """,
    )
    assert (tmp_path / 'pyproject.toml').read_text(encoding='utf-8') == expected
    # Should show both validators and insertions under the provider
    assert 'validators:' in result.output
    assert 'lint_toml' in result.output
    assert 'insertions:' in result.output
    assert '1 ok, 0 failed' in result.output


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
    _make_insertion_provider(
        tmp_path / 'alpha',
        """\
        def display_year(*, args):
            return '2026:alpha'
        return {'README.md': {'display-year': display_year}}""",
    )
    _make_insertion_provider(
        tmp_path / 'beta',
        """\
        def display_year(*, args):
            return '2026:beta'
        return {'README.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(
        tmp_path,
        {'alpha': './alpha', 'beta': './beta'},
        providers_order=['alpha', 'beta'],
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)
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
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def display_year(*, context, tag, args):
            return '2026'
        return {'README.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    run_repolish(['apply', '--check'], exit_code=0)


# -----------------------------------------------------------------------------
# Parametrized tests - common patterns consolidated
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='html_comment_basic',
            file_path='README.md',
            file_content="""\
            This is the current year

            <!-- repolish:on:year display-year -->
            <!-- repolish:off:year -->
            """,
            insertion_body="""\
            def display_year(*, context, tag, args):
                return '2026'
            return {'README.md': {'display-year': display_year}}""",
            expected_content="""\
            This is the current year

            <!-- repolish:on:year display-year -->
            2026
            <!-- repolish:off:year -->
            """,
            expected_output_checks=('insertions: ✓ ok (1 ok, 0 failed)',),
        ),
        TCase(
            name='hash_comment_toml',
            file_path='ruff.toml',
            file_content="""\
            # Ruff configuration
            line-length = 88

            # repolish:on:lint add_rules
            # repolish:off:lint
            """,
            insertion_body="""\
            def add_rules():
                return 'select = ["E", "W"]'
            return {'ruff.toml': {'add_rules': add_rules}}""",
            expected_content="""\
            # Ruff configuration
            line-length = 88

            # repolish:on:lint add_rules
            select = ["E", "W"]
            # repolish:off:lint
            """,
            expected_output_checks=('insertions: ✓ ok (1 ok, 0 failed)',),
        ),
        TCase(
            name='args_three_blocks',
            file_path='README.md',
            file_content="""\
            Controlled sections

            <!-- repolish:on:one display-mode on -->
            <!-- repolish:off:one -->

            <!-- repolish:on:two display-mode off -->
            <!-- repolish:off:two -->

            <!-- repolish:on:three display-mode maybe -->
            <!-- repolish:off:three -->
            """,
            insertion_body="""\
            def display_mode(*, args):
                flag = args[0]
                if flag == 'on':
                    return 'VISIBLE'
                if flag == 'off':
                    return 'HIDDEN'
                return f'UNKNOWN:{flag}'
            return {'README.md': {'display-mode': display_mode}}""",
            expected_content="""\
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
            expected_output_checks=('3 ok, 0 failed',),
        ),
        TCase(
            name='two_functions_same_file',
            file_path='README.md',
            file_content="""\
            Function registry demo

            <!-- repolish:on:first join-parts alpha beta gamma -->
            <!-- repolish:off:first -->

            <!-- repolish:on:second join-with-dashes one two three -->
            <!-- repolish:off:second -->
            """,
            insertion_body="""\
            def join_parts(a, b, c):
                return ':'.join((a, b, c))
            def join_with_dashes(a, b, c):
                return '-'.join((a, b, c))
            return {
                'README.md': {
                    'join-parts': join_parts,
                    'join-with-dashes': join_with_dashes,
                }
            }""",
            expected_content="""\
            Function registry demo

            <!-- repolish:on:first join-parts alpha beta gamma -->
            alpha:beta:gamma
            <!-- repolish:off:first -->

            <!-- repolish:on:second join-with-dashes one two three -->
            one-two-three
            <!-- repolish:off:second -->
            """,
            expected_output_checks=('2 ok, 0 failed',),
        ),
        TCase(
            name='report_exists',
            file_path='README.md',
            file_content="""\
            This is the current year

            <!-- repolish:on:year display-year -->
            <!-- repolish:off:year -->
            """,
            insertion_body="""\
            def display_year(*, context, tag, args):
                assert tag == 'year'
                assert args == ()
                assert context.repolish.workspace.mode in {'standalone', 'root', 'member'}
                return '2026'
            return {'README.md': {'display-year': display_year}}""",
            expected_content="""\
            This is the current year

            <!-- repolish:on:year display-year -->
            2026
            <!-- repolish:off:year -->
            """,
            expected_output_checks=(
                '◌ README.md  no file in stage',
                'insertions: ✓ ok (1 ok, 0 failed)',
            ),
            assert_fn=_assert_report_exists,
        ),
        TCase(
            name='failed_blocks_report',
            file_path='README.md',
            file_content="""\
            Mixed insertion blocks

            <!-- repolish:on:ok display-year -->
            <!-- repolish:off:ok -->

            <!-- repolish:on:bad missing-function -->
            <!-- repolish:off:bad -->
            """,
            insertion_body="""\
def display_year(*, args):
    return '2026'
return {'README.md': {'display-year': display_year}}""",
            expected_content="""\
            Mixed insertion blocks

            <!-- repolish:on:ok display-year -->
            2026
            <!-- repolish:off:ok -->

            <!-- repolish:on:bad missing-function -->
            <!-- repolish:off:bad -->
            """,
            expected_output_checks=('insertions: ✗ failed (1 ok, 1 failed)',),
            assert_fn=_assert_report_failed_blocks,
        ),
        TCase(
            name='check_drift',
            file_path='README.md',
            file_content="""\
            This is the current year

            <!-- repolish:on:year display-year -->
            1999
            <!-- repolish:off:year -->
            """,
            insertion_body="""\
            def display_year(*, context, tag, args):
                return '2026'
            return {'README.md': {'display-year': display_year}}""",
            expected_content="""\
            This is the current year

            <!-- repolish:on:year display-year -->
            1999
            <!-- repolish:off:year -->
            """,
            exit_code=2,
            check_mode=True,
            assert_fn=_assert_check_drift,
        ),
    ],
    ids=lambda c: c.name,
)
def test_provider_insertion_parametrized(
    case: TCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parametrized test for common insertion patterns."""
    _write(tmp_path / case.file_path, case.file_content)
    _make_insertion_provider(
        tmp_path / 'p',
        case.insertion_body,
        extra_imports=case.extra_imports,
        extra_methods=case.extra_methods,
    )
    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    exit_code = case.exit_code if case.exit_code is not None else 0
    args = ['apply', '--check'] if case.check_mode else ['apply']
    result = run_repolish(args, exit_code=exit_code)

    assert (tmp_path / case.file_path).read_text(encoding='utf-8') == dedent(
        case.expected_content,
    )

    for check in case.expected_output_checks:
        assert check in result.output

    if case.assert_fn:
        case.assert_fn(tmp_path, result)


def test_monorepo_root_mode_insertions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A root-mode handler can register insertions on workspace-owned files.

    This test mirrors test_monorepo_root_validator_stays_with_owning_provider_for_workspace_file
    but for insertions instead of validators.
    """
    repo = fixtures.monorepo_basic.stage(tmp_path)

    # Create a workspace-owned file at root with insertion markers
    (repo / 'README.workspace.md').write_text(
        '# Workspace README\n\n<!-- repolish:on:version insert-version -->\n<!-- repolish:off:version -->\n',
        encoding='utf-8',
    )

    # Create a provider that owns the workspace file (no template needed)
    (repo / 'workspace-provider').mkdir()
    (repo / 'workspace-provider' / 'repolish').mkdir(parents=True)
    (repo / 'workspace-provider' / 'repolish' / 'config.toml').write_text(
        'name = "workspace"\n',
        encoding='utf-8',
    )
    (repo / 'workspace-provider' / 'repolish.py').write_text(
        """
from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    pass


class WorkspaceProvider(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        # File already exists with markers; we just claim ownership
        return {}
""",
        encoding='utf-8',
    )

    # Create an insertion provider with root_mode handler
    (repo / 'insertion-provider').mkdir()
    (repo / 'insertion-provider' / 'repolish').mkdir(parents=True)
    (repo / 'insertion-provider' / 'repolish' / 'config.toml').write_text(
        'name = "insertion-provider"\n',
        encoding='utf-8',
    )
    (repo / 'insertion-provider' / 'repolish.py').write_text(
        """
from repolish import BaseContext, BaseInputs, ModeHandler, Provider


class Ctx(BaseContext):
    pass


class RootHandler(ModeHandler[Ctx, BaseInputs]):
    def create_file_insertions(self, ctx):
        def insert_version(*, context, tag, args):
            return '1.0.0'

        return {'README.workspace.md': {'insert-version': insert_version}}


class InsertionProvider(Provider[Ctx, BaseInputs]):
    root_mode = RootHandler

    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        return {}
""",
        encoding='utf-8',
    )

    # Update repolish.yaml to include both providers
    (repo / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'workspace-provider': {
                        'provider_root': './workspace-provider',
                    },
                    'insertion-provider': {
                        'provider_root': './insertion-provider',
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(repo)
    result = run_repolish(['apply'], exit_code=0)

    # File should exist and have insertion applied
    readme = repo / 'README.workspace.md'
    assert readme.exists()
    content = readme.read_text(encoding='utf-8')
    assert '1.0.0' in content
    assert '<!-- repolish:on:version insert-version -->' in content
    assert 'insertions:' in result.output
    assert '1 ok, 0 failed' in result.output
