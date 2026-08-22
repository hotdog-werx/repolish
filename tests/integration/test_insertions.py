"""Integration tests for provider-driven insertion blocks in non-owned files."""

from __future__ import annotations

import json
import os
import sys
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
    traceback_lines = data['diagnostics'][0]['traceback']
    assert traceback_lines is None or isinstance(traceback_lines, list)


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
        def display_year():
            return '2026'
        return {'missing.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)
    # File should not appear since it doesn't exist
    assert 'missing.md' not in result.output
    assert 'developer owned' not in result.output


def test_provider_insertion_check_missing_file_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check mode skips insertions for non-existent files."""
    # Do NOT create the target file
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def display_year():
            return '2026'
        return {'missing.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    # Check mode should succeed (no drift for missing file)
    result = run_repolish(['apply', '--check'], exit_code=0)
    assert 'missing.md' not in result.output


def test_provider_insertion_can_be_disabled_via_provider_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider can disable one insertion function through overrides."""
    _write(
        tmp_path / 'README.md',
        """\
        Mixed blocks

        <!-- repolish:on:one render-a -->
        KEEP_A
        <!-- repolish:off:one -->

        <!-- repolish:on:two render-b -->
        KEEP_B
        <!-- repolish:off:two -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def render_a():
            return 'A_NEW'

        def render_b():
            return 'B_NEW'

        return {'README.md': {'render-a': render_a, 'render-b': render_b}}""",
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'insertions': {
                                'README.md': {
                                    'render-a': False,
                                },
                            },
                        },
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    content = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'KEEP_A' in content
    assert 'A_NEW' not in content
    assert 'B_NEW' in content
    assert 'insertions: ✓ ok (1 ok, 0 failed, 1 disabled)' in result.output

    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.p.json'
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['disabled_blocks'] == 1
    assert any(d.get('kind') == 'disabled' for d in data['diagnostics'])


def test_provider_insertion_file_can_be_disabled_via_provider_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider can disable all insertions for a file through overrides."""
    _write(
        tmp_path / 'README.md',
        """\
        File-level disable

        <!-- repolish:on:one render-a -->
        KEEP_A
        <!-- repolish:off:one -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def render_a():
            return 'A_NEW'

        return {'README.md': {'render-a': render_a}}""",
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'insertions': {
                                'README.md': False,
                            },
                        },
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    content = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'KEEP_A' in content
    assert 'A_NEW' not in content
    assert 'insertions:' not in result.output


def test_provider_insertion_paused_file_skips_apply_and_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """paused_files prevents insertion apply and insertion drift checks for that file."""
    _write(
        tmp_path / 'README.md',
        """\
        Paused insertion

        <!-- repolish:on:one render-a -->
        KEEP_A
        <!-- repolish:off:one -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def render_a():
            return 'A_NEW'

        return {'README.md': {'render-a': render_a}}""",
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                    },
                },
                'paused_files': ['README.md'],
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    run_repolish(['apply'], exit_code=0)
    content = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'KEEP_A' in content
    assert 'A_NEW' not in content

    run_repolish(['apply', '--check'], exit_code=0)


def test_provider_insertion_can_disable_single_block_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tag override can disable one block while keeping another block on the same function active."""
    _write(
        tmp_path / 'README.md',
        """\
        Same function, two tags

        <!-- repolish:on:one render-mode on -->
        KEEP_ONE
        <!-- repolish:off:one -->

        <!-- repolish:on:two render-mode off -->
        KEEP_TWO
        <!-- repolish:off:two -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def render_mode(mode: str):
            return f'VALUE_{mode.upper()}'

        return {'README.md': {'render-mode': render_mode}}""",
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'insertions': {
                                'README.md': {
                                    'tag:two': False,
                                },
                            },
                        },
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    content = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'VALUE_ON' in content
    assert 'KEEP_TWO' in content
    assert 'VALUE_OFF' not in content
    assert 'insertions: ✓ ok (1 ok, 0 failed, 1 disabled)' in result.output

    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.p.json'
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['disabled_blocks'] == 1
    disabled_entries = [d for d in data['diagnostics'] if d.get('kind') == 'disabled']
    assert disabled_entries
    assert disabled_entries[0]['tag'] == 'two'
    assert disabled_entries[0]['function'] == 'render-mode'


def test_provider_insertion_function_disable_applies_to_all_matching_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Function-level disable pauses all blocks that call that function in a file."""
    _write(
        tmp_path / 'README.md',
        """\
        Same function twice

        <!-- repolish:on:one render-mode on -->
        KEEP_ONE
        <!-- repolish:off:one -->

        <!-- repolish:on:two render-mode off -->
        KEEP_TWO
        <!-- repolish:off:two -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def render_mode(mode: str):
            return f'VALUE_{mode.upper()}'

        return {'README.md': {'render-mode': render_mode}}""",
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'insertions': {
                                'README.md': {
                                    'render_mode': False,
                                },
                            },
                        },
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    content = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'KEEP_ONE' in content
    assert 'KEEP_TWO' in content
    assert 'VALUE_ON' not in content
    assert 'VALUE_OFF' not in content
    assert 'insertions: ✓ ok (0 ok, 0 failed, 2 disabled)' in result.output


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


def test_provider_insertion_function_signature_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test all insertion function signature variants in a single file."""
    # Create a file with insertion blocks covering signature dispatch variants
    _write(
        tmp_path / 'config.txt',
        """\
        # Configuration file with multiple insertion styles

        # repolish:on zero_arg_func
        PLACEHOLDER_ZERO
        # repolish:off

        # repolish:on positional_func hello world
        PLACEHOLDER_POSITIONAL
        # repolish:off

        # repolish:on single_arg_positional_func hello_single
        PLACEHOLDER_SINGLE_ARG_POSITIONAL
        # repolish:off

        # repolish:on varargs_func a b c d
        PLACEHOLDER_VARARGS
        # repolish:off

        # repolish:on:ctx context_func
        PLACEHOLDER_CONTEXT
        # repolish:off:ctx

        # repolish:on:block block_param_func
        PLACEHOLDER_BLOCK_PARAM
        # repolish:off:block

        # repolish:on:combo combo_func value_one value_two
        PLACEHOLDER_COMBO
        # repolish:off:combo

        # repolish:on:named named_args_func third-arg=value3 arg-one='this is value1'
        PLACEHOLDER_NAMED_ARGS
        # repolish:off:named

        # repolish:on empty_tag_func
        PLACEHOLDER_EMPTY_TAG
        # repolish:off
        """,
    )

    _make_insertion_provider(
        tmp_path / 'p',
        """\
        from repolish.insertions import InsertionBlock, BlockContext

        def zero_arg_func():
            return 'zero-arg-result'

        def positional_func(arg1: str, arg2: str):
            return f'positional:{arg1}:{arg2}'

        def single_arg_positional_func(arg1: str):
            return f'single-positional:{arg1}'

        def varargs_func(*args):
            return 'varargs:' + '-'.join(args)

        def context_func(*, block_context: BlockContext):
            return f'context-func:tag={block_context.tag}:repo={block_context.repolish.repo.name}'

        def block_param_func(*, insertion_block: InsertionBlock):
            return f'block-param-func:fn={insertion_block.function}:args={",".join(insertion_block.args)}'

        def combo_func(
            arg1: str,
            arg2: str,
            *,
            block_context: BlockContext,
            insertion_block: InsertionBlock,
        ):
            return (
                f'combo:{arg1}:{arg2}:'
                f'tag={block_context.tag}:'
                f'fn={insertion_block.function}'
            )

        def named_args_func(
            arg_one: str | None,
            arg_two: str | None,
            third_arg: str,
        ):
            return f'named:{arg_one}:{arg_two}:{third_arg}'

        def empty_tag_func():
            return 'empty-tag-works'

        return {
            'config.txt': {
                'zero_arg_func': zero_arg_func,
                'positional_func': positional_func,
                'single_arg_positional_func': single_arg_positional_func,
                'varargs_func': varargs_func,
                'context_func': context_func,
                'block_param_func': block_param_func,
                'combo_func': combo_func,
                'named_args_func': named_args_func,
                'empty_tag_func': empty_tag_func,
            }
        }""",
        extra_imports='from repolish import InsertionBlock, BlockContext',
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected = dedent(
        """\
        # Configuration file with multiple insertion styles

        # repolish:on zero_arg_func
        zero-arg-result
        # repolish:off

        # repolish:on positional_func hello world
        positional:hello:world
        # repolish:off

        # repolish:on single_arg_positional_func hello_single
        single-positional:hello_single
        # repolish:off

        # repolish:on varargs_func a b c d
        varargs:a-b-c-d
        # repolish:off

        # repolish:on:ctx context_func
        context-func:tag=ctx:repo=test-repo
        # repolish:off:ctx

        # repolish:on:block block_param_func
        block-param-func:fn=block_param_func:args=
        # repolish:off:block

        # repolish:on:combo combo_func value_one value_two
        combo:value_one:value_two:tag=combo:fn=combo_func
        # repolish:off:combo

        # repolish:on:named named_args_func third-arg=value3 arg-one='this is value1'
        named:this is value1:None:value3
        # repolish:off:named

        # repolish:on empty_tag_func
        empty-tag-works
        # repolish:off
        """,
    )
    assert (tmp_path / 'config.txt').read_text(encoding='utf-8') == expected
    assert 'insertions: ✓ ok (9 ok, 0 failed)' in result.output


def test_provider_insertion_named_args_validation_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Named insertion args validate keys and omitted required parameters."""
    _write(
        tmp_path / 'README.md',
        """\
        Named-arg validation

        <!-- repolish:on:one render-config bad-key=oops required-arg=ok -->
        <!-- repolish:off:one -->

        <!-- repolish:on:two render-config optional-arg=only -->
        <!-- repolish:off:two -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def render_config(required_arg: str, optional_arg: str | None):
            return f'rendered:{required_arg}:{optional_arg}'

        return {'README.md': {'render-config': render_config}}""",
    )
    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    assert 'insertions: ✗ failed (0 ok, 2 failed)' in result.output

    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.p.json'
    assert report.exists()
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['failed_blocks'] == 2
    assert len(data['diagnostics']) == 2
    messages = [d['message'] for d in data['diagnostics']]
    assert any('Unknown named insertion args' in msg for msg in messages)
    assert any("Missing named insertion arg 'required_arg'" in msg for msg in messages)


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


def test_provider_template_can_ship_insertion_markers_for_user_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider template can include insertion markers that are rendered after mapping."""
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def render_status(value: str):
            return f'STATUS={value}'

        return {'README.md': {'render-status': render_status}}""",
        extra_imports='from repolish.providers.models import TemplateMapping',
        extra_methods="""\
def create_file_mappings(self, context):
    return {
        'README.md': TemplateMapping(source_template='README.md.jinja'),
    }
""",
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'README.md.jinja',
        """\
        Provider-owned template with insertion marker

        <!-- repolish:on:status render-status ready -->
        <!-- repolish:off:status -->
        """,
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)
    expected = dedent(
        """\
        Provider-owned template with insertion marker

        <!-- repolish:on:status render-status ready -->
        STATUS=ready
        <!-- repolish:off:status -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


def test_provider_insertion_targets_can_be_extended_from_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project config can extend provider insertion target files conservatively."""
    _write(
        tmp_path / 'README.md',
        """\
        Primary file

        <!-- repolish:on:src generate-uv-sources local -->
        <!-- repolish:off:src -->
        """,
    )
    _write(
        tmp_path / 'docs.md',
        """\
        Secondary file

        <!-- repolish:on:src generate-uv-sources github -->
        <!-- repolish:off:src -->
        """,
    )

    _make_insertion_provider(
        tmp_path / 'p',
        """\
        return ['README.md']""",
        extra_methods="""
def create_insertion_registry(self, context):
    def generate_uv_sources(source: str):
        return f'sources={source}'

    return {'generate-uv-sources': generate_uv_sources}
""",
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'insertions_extend_files': ['docs.md'],
                        },
                    },
                },
            },
            indent=4,
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected_readme = dedent(
        """\
        Primary file

        <!-- repolish:on:src generate-uv-sources local -->
        sources=local
        <!-- repolish:off:src -->
        """,
    )
    expected_docs = dedent(
        """\
        Secondary file

        <!-- repolish:on:src generate-uv-sources github -->
        sources=github
        <!-- repolish:off:src -->
        """,
    )

    assert (tmp_path / 'README.md').read_text(
        encoding='utf-8',
    ) == expected_readme
    assert (tmp_path / 'docs.md').read_text(encoding='utf-8') == expected_docs
    # There should be two insertions applied, one for each file
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


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
        def display_year():
            return '2026:alpha'
        return {'README.md': {'display-year': display_year}}""",
    )
    _make_insertion_provider(
        tmp_path / 'beta',
        """\
        def display_year():
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
    assert 'developer owned' in result.output
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected


def test_provider_insertion_provider_qualified_marker_falls_back_to_unqualified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-qualified marker falls back to unqualified function lookup when needed."""
    _write(
        tmp_path / 'README.md',
        """\
        Qualified fallback

        <!-- repolish:on:one unknown:display-year -->
        <!-- repolish:off:one -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def display_year():
            return '2026'
        return {'README.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected = dedent(
        """\
        Qualified fallback

        <!-- repolish:on:one unknown:display-year -->
        2026
        <!-- repolish:off:one -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert 'README.md' in result.output


def test_provider_insertion_shared_registry_targets_list_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers can register a shared insertion registry and target files via list[str]."""
    _write(
        tmp_path / 'README.md',
        """\
        Shared insertion registry

        <!-- repolish:on:uv generate-uv-sources local -->
        <!-- repolish:off:uv -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        return ['README.md']""",
        extra_methods="""
def create_insertion_registry(self, context):
    def generate_uv_sources(mode: str):
        return f'sources={mode}'

    return {'generate-uv-sources': generate_uv_sources}
""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected = dedent(
        """\
        Shared insertion registry

        <!-- repolish:on:uv generate-uv-sources local -->
        sources=local
        <!-- repolish:off:uv -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


def test_provider_insertion_list_mode_only_applies_to_declared_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List-mode insertion targets do not apply to extra files without config extension."""
    _write(
        tmp_path / 'README.md',
        """\
        Primary target

        <!-- repolish:on:uv generate-uv-sources local -->
        <!-- repolish:off:uv -->
        """,
    )
    _write(
        tmp_path / 'docs.md',
        """\
        Non-target file

        <!-- repolish:on:uv generate-uv-sources github -->
        <!-- repolish:off:uv -->
        """,
    )

    _make_insertion_provider(
        tmp_path / 'p',
        """\
        return ['README.md']""",
        extra_methods="""
def create_insertion_registry(self, context):
    def generate_uv_sources(mode: str):
        return f'sources={mode}'

    return {'generate-uv-sources': generate_uv_sources}
""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected_readme = dedent(
        """\
        Primary target

        <!-- repolish:on:uv generate-uv-sources local -->
        sources=local
        <!-- repolish:off:uv -->
        """,
    )
    expected_docs = dedent(
        """\
        Non-target file

        <!-- repolish:on:uv generate-uv-sources github -->
        <!-- repolish:off:uv -->
        """,
    )

    assert (tmp_path / 'README.md').read_text(
        encoding='utf-8',
    ) == expected_readme
    assert (tmp_path / 'docs.md').read_text(encoding='utf-8') == expected_docs
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


def test_provider_insertion_shared_registry_on_rendered_template_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shared insertion registry can target a provider-rendered template output file."""
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        return ['README.md']""",
        extra_imports='from repolish.providers.models import TemplateMapping',
        extra_methods="""
def create_file_mappings(self, context):
    return {
        'README.md': TemplateMapping(source_template='README.md.jinja'),
    }

def create_insertion_registry(self, context):
    def render_status(state: str):
        return f'STATUS={state}'

    return {'render-status': render_status}
""",
    )

    _write(
        tmp_path / 'p' / 'repolish' / 'README.md.jinja',
        """\
        Rendered file with insertion marker

        <!-- repolish:on:status render-status ready -->
        <!-- repolish:off:status -->
        """,
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected = dedent(
        """\
        Rendered file with insertion marker

        <!-- repolish:on:status render-status ready -->
        STATUS=ready
        <!-- repolish:off:status -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


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
        def display_year():
            return '2026'
        return {'README.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply', '--check'], exit_code=0)
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


def test_provider_insertion_forwardref_annotation_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ForwardRef InsertionBlock annotations are recognized for injection."""
    _write(
        tmp_path / 'README.md',
        """\
        ForwardRef insertion

        <!-- repolish:on:one render-forward -->
        <!-- repolish:off:one -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        from typing import ForwardRef

        def render_forward(*, injected):
            return f'forward:{injected.function}'

        render_forward.__annotations__['injected'] = ForwardRef('InsertionBlock')

        return {'README.md': {'render-forward': render_forward}}""",
    )
    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    expected = dedent(
        """\
        ForwardRef insertion

        <!-- repolish:on:one render-forward -->
        forward:render-forward
        <!-- repolish:off:one -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert 'insertions: ✓ ok (1 ok, 0 failed)' in result.output


def test_provider_insertion_rejects_varargs_with_typed_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Varargs cannot be combined with typed BlockContext/InsertionBlock injection."""
    _write(
        tmp_path / 'README.md',
        """\
        Invalid insertion signature

        <!-- repolish:on:one bad-renderer x y -->
        <!-- repolish:off:one -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def bad_renderer(*args, insertion_block: 'InsertionBlock'):
            return f'should-not-render:{insertion_block.function}:{"|".join(args)}'

        return {'README.md': {'bad-renderer': bad_renderer}}""",
        extra_imports='from repolish import InsertionBlock',
    )
    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    # Content remains unchanged because insertion rendering failed.
    expected = dedent(
        """\
        Invalid insertion signature

        <!-- repolish:on:one bad-renderer x y -->
        <!-- repolish:off:one -->
        """,
    )
    assert (tmp_path / 'README.md').read_text(encoding='utf-8') == expected
    assert 'insertions: ✗ failed (0 ok, 1 failed)' in result.output

    report = tmp_path / '.repolish' / '_' / 'insertions' / 'insertions.README.md.p.json'
    assert report.exists()
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['failed_blocks'] == 1
    assert data['functions'] == ['bad-renderer']
    assert data['diagnostics']
    assert 'cannot combine *args with BlockContext/InsertionBlock annotations' in data['diagnostics'][0]['message']
    traceback_lines = data['diagnostics'][0]['traceback']
    assert isinstance(traceback_lines, list)
    assert traceback_lines
    assert any('bad_renderer' in line for line in traceback_lines)


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
            def display_year():
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
            def display_mode(flag: str):
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
            def display_year(*, block_context: BlockContext):
                assert block_context.tag == 'year'
                assert block_context.args == ()
                assert block_context.repolish.workspace.mode in {'standalone', 'root', 'member'}
                return '2026'
            return {'README.md': {'display-year': display_year}}""",
            extra_imports='from repolish import BlockContext',
            expected_content="""\
            This is the current year

            <!-- repolish:on:year display-year -->
            2026
            <!-- repolish:off:year -->
            """,
            expected_output_checks=(
                '◌ README.md  developer owned',
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
def display_year():
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
            def display_year():
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
        def insert_version():
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


def test_monorepo_root_mode_insertions_shared_registry_list_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A root-mode handler can register list-mode insertion targets via shared registry."""
    repo = fixtures.monorepo_basic.stage(tmp_path)

    (repo / 'README.workspace.md').write_text(
        '# Workspace README\n\n<!-- repolish:on:version insert-version -->\n<!-- repolish:off:version -->\n',
        encoding='utf-8',
    )

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
        return {}
""",
        encoding='utf-8',
    )

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
        return ['README.workspace.md']

    def create_insertion_registry(self, ctx):
        def insert_version():
            return '2.0.0'

        return {'insert-version': insert_version}


class InsertionProvider(Provider[Ctx, BaseInputs]):
    root_mode = RootHandler

    def create_context(self):
        return Ctx()

    def create_file_mappings(self, ctx):
        return {}
""",
        encoding='utf-8',
    )

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

    content = (repo / 'README.workspace.md').read_text(encoding='utf-8')
    assert '2.0.0' in content
    assert '<!-- repolish:on:version insert-version -->' in content
    assert 'insertions:' in result.output
    assert '1 ok, 0 failed' in result.output


def test_provider_insertion_with_post_process_formatting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insertions are formatted by post_process commands after being applied."""
    # Create a file with an insertion marker
    _write(
        tmp_path / 'test.txt',
        """\
        # Header
        <!-- repolish:on:spaces insert-spaces -->
        <!-- repolish:off:spaces -->
        """,
    )

    # Create provider that inserts content with leading spaces
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def insert_spaces():
            return '     has_spaces'
        return {'test.txt': {'insert-spaces': insert_spaces}}""",
    )

    # Create a post_process script that strips leading whitespace
    (tmp_path / 'strip_spaces.py').write_text(
        'import sys\n'
        'for f in sys.argv[1:]:\n'
        '    lines = open(f).readlines()\n'
        "    open(f, 'w').write(''.join(line.lstrip() for line in lines))\n",
        encoding='utf-8',
    )
    # Create repolish.yaml with post_process that runs the script
    (tmp_path / 'repolish.yaml').write_text(
        '{"providers": {"p": {"provider_root": "./p"}}, "post_process": ["python strip_spaces.py test.txt"]}',
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    # Run WITHOUT --skip-post-process: spaces should be stripped
    result = run_repolish(['apply'], exit_code=0)
    content = (tmp_path / 'test.txt').read_text(encoding='utf-8')
    assert 'has_spaces' in content
    assert '     has_spaces' not in content

    # Reset the file to have leading spaces again
    _write(
        tmp_path / 'test.txt',
        """\
        # Header
        <!-- repolish:on:spaces insert-spaces -->
        <!-- repolish:off:spaces -->
        """,
    )

    # Run WITH --skip-post-process: spaces should NOT be stripped
    run_repolish(['apply', '--skip-post-process'], exit_code=0)
    content_skip = (tmp_path / 'test.txt').read_text(encoding='utf-8')
    # The insertion content should still have leading spaces
    assert '     has_spaces' in content_skip
    assert 'insertions:' in result.output
    assert '1 ok, 0 failed' in result.output


def test_provider_insertion_empty_tag_syntax(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty tag names work: <!-- repolish:on: func --> ... <!-- repolish:off: -->."""
    test_dir = tmp_path / 'empty_tag_test'
    test_dir.mkdir()

    # Create a file with empty-tag syntax (colon but no tag name)
    _write(
        test_dir / 'test.md',
        """\
        # Header

        <!-- repolish:on: display-year -->
        <!-- repolish:off: -->

        More content
        """,
    )

    # Create provider
    _make_insertion_provider(
        test_dir / 'p',
        """\
        def display_year():
            return '2026'
        return {'test.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(test_dir, {'p': './p'})

    monkeypatch.chdir(test_dir)
    init_git_repo(test_dir)
    result = run_repolish(['apply'], exit_code=0)

    content = (test_dir / 'test.md').read_text(encoding='utf-8')
    assert '2026' in content
    assert 'insertions:' in result.output
    assert '1 ok, 0 failed' in result.output


def test_provider_insertion_no_colon_syntax(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No colon syntax works: <!-- repolish:on func --> ... <!-- repolish:off -->."""
    test_dir = tmp_path / 'no_colon_test'
    test_dir.mkdir()

    # Create a file with no-colon syntax
    _write(
        test_dir / 'test.md',
        """\
        # Header

        <!-- repolish:on display-year -->
        <!-- repolish:off -->

        More content
        """,
    )

    # Create provider
    _make_insertion_provider(
        test_dir / 'p',
        """\
        def display_year():
            return '2026'
        return {'test.md': {'display-year': display_year}}""",
    )

    _write_repolish_yaml(test_dir, {'p': './p'})

    monkeypatch.chdir(test_dir)
    init_git_repo(test_dir)
    result = run_repolish(['apply'], exit_code=0)

    content = (test_dir / 'test.md').read_text(encoding='utf-8')
    assert '2026' in content
    assert 'insertions:' in result.output
    assert '1 ok, 0 failed' in result.output


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='Simulates Unix-style installed CLI execution from PATH.',
)
def test_post_process_applies_in_both_apply_and_check_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies post_process runs on both apply and check mode.

    When running `repolish apply`, post_process commands are executed and files
    are formatted. When running `repolish apply --check`, post_process must also
    run on staged files before comparison, otherwise false drift is detected.

    This test verifies the fix: after a successful apply (with post_process),
    running check mode passes because both apply and check run post_process.
    """
    # Create a file with an insertion marker
    _write(
        tmp_path / 'test.txt',
        """\
        # Header
        <!-- repolish:on:spaces insert-spaces -->
        <!-- repolish:off:spaces -->
        """,
    )

    # Create provider with insertion + a regular mapped template file
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        def insert_spaces():
            return '     has_spaces'
        return {'test.txt': {'insert-spaces': insert_spaces}}""",
        extra_imports='from repolish.providers.models import TemplateMapping',
        extra_methods="""\
def create_file_mappings(self, context):
    return {
        'mapped.txt': TemplateMapping(source_template='mapped.txt.jinja'),
    }
""",
    )

    # Create a regular template source that also needs post-processing
    _write(
        tmp_path / 'p' / 'repolish' / 'mapped.txt.jinja',
        """\
             mapped_from_template
        """,
    )

    # Create a post_process script that strips leading whitespace from all txt files in cwd
    strip_script = tmp_path / 'strip_spaces.py'
    strip_script.write_text(
        '#!/usr/bin/env python3\n'
        'import glob\n'
        'for f in glob.glob("*.txt"):\n'
        '    lines = open(f).readlines()\n'
        "    open(f, 'w').write(''.join(line.lstrip() for line in lines))\n",
        encoding='utf-8',
    )
    strip_script.chmod(0o755)

    # Simulate an installed formatter binary discoverable via PATH.
    old_path = os.environ.get('PATH', '')
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{old_path}')

    (tmp_path / 'repolish.yaml').write_text(
        '{"providers": {"p": {"provider_root": "./p"}}, "post_process": ["strip_spaces.py"]}',
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    # Run apply: insertion should be applied AND post-processed
    run_repolish(['apply'], exit_code=0)

    # Verify insertion file has been post-processed (no leading spaces)
    content = (tmp_path / 'test.txt').read_text(encoding='utf-8')
    assert 'has_spaces' in content
    assert '     has_spaces' not in content

    # Verify mapped template file is also post-processed (no leading spaces)
    mapped_content = (tmp_path / 'mapped.txt').read_text(encoding='utf-8')
    assert 'mapped_from_template' in mapped_content
    assert '     mapped_from_template' not in mapped_content

    # FIXED: Running check mode now passes because post_process IS applied during check
    run_repolish(['apply', '--check', '-vv'], exit_code=0)


def test_provider_insertion_receives_file_path_in_block_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insertion functions receive file_path via BlockContext and InsertionBlock."""
    _write(
        tmp_path / 'README.md',
        """\
        File path test

        <!-- repolish:on:path-test show-path -->
        PLACEHOLDER
        <!-- repolish:off:path-test -->

        <!-- repolish:on:block-path show-block-path -->
        PLACEHOLDER2
        <!-- repolish:off:block-path -->
        """,
    )
    _make_insertion_provider(
        tmp_path / 'p',
        """\
        from repolish import BlockContext, InsertionBlock

        def show_path(*, ctx: BlockContext):
            # Verify file_path is available in BlockContext
            assert ctx.file_path == 'README.md', f"Expected 'README.md', got {ctx.file_path!r}"
            assert ctx.insertion_block is not None
            assert ctx.insertion_block.file_path == 'README.md'
            return f'file-is:{ctx.file_path}'

        def show_block_path(*, block: InsertionBlock):
            # Verify file_path is available in InsertionBlock
            assert block.file_path == 'README.md', f"Expected 'README.md', got {block.file_path!r}"
            return f'block-file-is:{block.file_path}'

        return {
            'README.md': {
                'show-path': show_path,
                'show-block-path': show_block_path,
            }
        }""",
        extra_imports='from repolish import BlockContext, InsertionBlock',
    )

    _write_repolish_yaml(tmp_path, {'p': './p'})

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'], exit_code=0)

    content = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'file-is:README.md' in content
    assert 'block-file-is:README.md' in content
    assert 'insertions: ✓ ok (2 ok, 0 failed)' in result.output
