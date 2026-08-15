"""Integration tests for provider-owned file validators.

These verify the public behavior a user sees when a provider contributes
validators, when config disables a validator, and when a validator fails after
rendering.
"""

from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

from repolish.providers.models import ValidationStatus

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _make_validator_provider(
    directory: Path,
    *,
    fail: bool = False,
    fail_message: str = 'file failed validation',
    status: ValidationStatus | str = ValidationStatus.ERROR,
) -> None:
    """Create a minimal provider with a file mapping and a validator.

    The validator runs against the rendered file in the project working tree and
    returns an explicit validation status. ``fail`` is a convenience for legacy
    boolean-style tests, while ``status`` makes the intended semantics obvious.
    """
    resolved_status = ValidationStatus(status)
    if fail and resolved_status == ValidationStatus.PASS:
        resolved_status = ValidationStatus.ERROR

    _write(directory / 'repolish' / 'config.toml', 'name = "demo"\n')
    _write(
        directory / 'repolish.py',
        dedent(f"""\
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models import ValidationResult, ValidationStatus

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, ctx):
                return {{'config.toml': 'config.toml'}}

            def create_file_validators(self, ctx):
                def lint(context, path):
                    return ValidationResult(
                        status={resolved_status.value!r},
                        message={fail_message!r},
                        path=str(path),
                        validator_name='lint',
                    )

                def schema(context, path):
                    return ValidationResult(
                        status=ValidationStatus.PASS,
                        message='schema ok',
                        path=str(path),
                        validator_name='schema',
                    )

                return {{'config.toml': {{'lint': lint, 'schema': schema}}}}
        """),
    )


def test_validator_can_be_disabled_via_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validator can be explicitly disabled through provider overrides."""
    _make_validator_provider(tmp_path / 'p')

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'validators': {'config.toml': {'lint': False}},
                        },
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])
    assert (tmp_path / 'config.toml').exists()
    assert 'lint' in result.output
    assert 'disabled' in result.output
    assert 'schema' in result.output


def test_provider_default_disabled_validator_can_be_enabled_via_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider default-off validator can be explicitly opted back in by config."""
    _make_validator_provider(tmp_path / 'p')

    (tmp_path / 'p' / 'repolish.py').write_text(
        dedent("""\
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models import (
            FileValidatorOptions,
            FileValidatorSpec,
            ValidationResult,
        )

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, ctx):
                return {'config.toml': 'config.toml'}

            def create_file_validators(self, ctx):
                def lint(context, path):
                    return ValidationResult(
                        status='pass',
                        message='lint ok',
                        path=str(path),
                        validator_name='lint',
                    )

                return {
                    'config.toml': {
                        'lint': FileValidatorSpec(
                            fn=lint,
                            options=FileValidatorOptions(enabled=False),
                        ),
                    }
                }
        """),
        encoding='utf-8',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'validators': {'config.toml': {'lint': True}},
                        },
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])
    assert (tmp_path / 'config.toml').exists()
    output = result.output
    assert 'lint' in output
    assert 'disabled' not in output
    assert '✓ lint' in output


def test_provider_default_disabled_validator_stays_disabled_when_not_opted_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider default-off validator remains disabled unless the repo opts in."""
    _make_validator_provider(tmp_path / 'p')

    (tmp_path / 'p' / 'repolish.py').write_text(
        dedent("""\
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models import (
            FileValidatorOptions,
            FileValidatorSpec,
            ValidationResult,
        )

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, ctx):
                return {'config.toml': 'config.toml'}

            def create_file_validators(self, ctx):
                def lint(context, path):
                    return ValidationResult(
                        status='pass',
                        message='lint ok',
                        path=str(path),
                        validator_name='lint',
                    )

                return {
                    'config.toml': {
                        'lint': FileValidatorSpec(
                            fn=lint,
                            options=FileValidatorOptions(enabled=False),
                        ),
                    }
                }
        """),
        encoding='utf-8',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    assert (tmp_path / 'config.toml').exists()
    output = result.output
    assert 'lint' in output
    assert 'disabled' in output
    assert 'lint ok' not in output


def test_validators_on_paused_file_are_marked_paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Files in paused_files skip validation and display a paused status."""
    _make_validator_provider(
        tmp_path / 'p',
        fail=True,
        fail_message='should not run because file is paused',
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {'p': {'provider_root': './p'}},
                'paused_files': ['config.toml'],
            },
        ),
        encoding='utf-8',
    )

    (tmp_path / 'config.toml').write_text(
        'free of repolish control',
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    assert (tmp_path / 'config.toml').exists()
    output = result.output
    assert 'lint' not in output
    assert 'paused' in output


def test_validators_from_multiple_providers_can_coexist_on_same_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different providers may contribute validators for the same file without clobbering each other."""
    _make_validator_provider(tmp_path / 'p')

    q_dir = tmp_path / 'q'
    _write(
        q_dir / 'repolish' / 'config.toml',
        '# generated by q\nname = "demo"\n',
    )
    _write(
        q_dir / 'repolish.py',
        dedent("""\
            from repolish import BaseContext, Provider, BaseInputs
            from repolish.providers.models import ValidationResult

            class Ctx(BaseContext):
                pass

            class P(Provider[Ctx, BaseInputs]):
                def create_context(self):
                    return Ctx()

                def create_file_mappings(self, ctx):
                    return {'config.toml': 'config.toml'}

                def create_file_validators(self, ctx):
                    def header(context, path):
                        text = path.read_text(encoding='utf-8')
                        return ValidationResult(
                            status='pass' if text.startswith('# generated by q\\n') else 'error',
                            message='missing q header',
                            path=str(path),
                            validator_name='header',
                        )

                    def endline(context, path):
                        text = path.read_text(encoding='utf-8')
                        return ValidationResult(
                            status='pass' if text.endswith('\\n') else 'error',
                            message='missing trailing newline',
                            path=str(path),
                            validator_name='endline',
                        )

                    return {'config.toml': {'header': header, 'endline': endline}}
            """),
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'validators': {'config.toml': {'lint': False}},
                        },
                    },
                    'q': {'provider_root': './q'},
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    assert (tmp_path / 'config.toml').exists()
    output = result.output
    assert 'validators' in output
    assert 'lint' in output
    assert 'disabled' in output
    assert 'schema' in output
    assert 'header' in output
    assert 'endline' in output


def test_validator_can_target_existing_project_file_without_file_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider can validate an existing project file even when it renders nothing."""
    (tmp_path / 'README.md').write_text('# Demo project\n', encoding='utf-8')
    _write(tmp_path / 'p' / 'repolish' / 'config.toml', 'name = "demo"\n')
    _write(
        tmp_path / 'p' / 'repolish.py',
        dedent("""\
        from pathlib import Path

        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models import ValidationResult

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, ctx):
                return {}

            def create_file_validators(self, ctx):
                def lint(context, path: Path):
                    text = path.read_text(encoding='utf-8')
                    return ValidationResult(
                        status='pass' if 'Demo' in text else 'error',
                        message='README.md must mention the project name',
                        path=str(path),
                        validator_name='lint',
                    )

                return {'README.md': {'lint': lint}}
        """),
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])
    assert (tmp_path / 'README.md').exists()
    output = result.output
    assert 'README.md' in output
    assert 'no file in stage' in output
    assert 'lint' in output
    assert '✓ lint' in output


def test_validator_override_branches_cover_missing_and_empty_registries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repo overrides cover callable re-enable, missing registries, and empty registries."""
    _write(tmp_path / 'p' / 'repolish' / 'config.toml', 'name = "demo"\n')
    _write(tmp_path / 'p' / 'repolish' / 'empty.toml', 'name = "demo"\n')
    _write(
        tmp_path / 'p' / 'repolish.py',
        dedent("""\
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models import ValidationResult

        class Ctx(BaseContext):
            pass

        class P(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, ctx):
                return {
                    'config.toml': 'config.toml',
                    'empty.toml': 'empty.toml',
                }

            def create_file_validators(self, ctx):
                def lint(context, path):
                    return ValidationResult(
                        status='pass',
                        message='lint ok',
                        path=str(path),
                        validator_name='lint',
                    )

                return {
                    'config.toml': {'lint': lint},
                    'empty.toml': {},
                }
        """),
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps(
            {
                'providers': {
                    'p': {
                        'provider_root': './p',
                        'overrides': {
                            'validators': {
                                'config.toml': {'lint': True},
                                'empty.toml': {'lint': False},
                                'missing.toml': {'lint': False},
                            },
                        },
                    },
                },
            },
        ),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    assert (tmp_path / 'config.toml').exists()
    assert (tmp_path / 'empty.toml').exists()
    assert 'lint' in result.output


def test_validator_failure_warns_but_does_not_fail_without_fail_on_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warnings are visible in the summary and do not abort by default."""
    _make_validator_provider(
        tmp_path / 'p',
        fail=True,
        fail_message='bad config',
        status=ValidationStatus.WARNING,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply'])

    assert (tmp_path / 'config.toml').exists()
    output = result.output
    assert 'validators' in output
    assert 'lint' in output
    assert 'bad config' in output
    assert '⚠' in output


def test_validator_failure_exits_nonzero_in_fail_on_warnings_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-on-warnings mode turns warnings into a non-zero CLI exit and prints the reason."""
    _make_validator_provider(
        tmp_path / 'p',
        fail=True,
        fail_message='bad config',
        status=ValidationStatus.ERROR,
    )

    (tmp_path / 'repolish.yaml').write_text(
        json.dumps({'providers': {'p': {'provider_root': './p'}}}),
        encoding='utf-8',
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)
    result = run_repolish(['apply', '--fail-on-warnings'], exit_code=1)

    assert (tmp_path / 'config.toml').exists()
    output = result.output.lower()
    assert 'validators' in output
    assert 'lint' in output
    assert 'bad config' in output
    assert 'error' in output or 'failed' in output
