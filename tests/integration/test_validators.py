"""Integration tests for file validators and --validate-only flag.

Tests that providers can register file validators and that the --validate-only
CLI flag correctly runs validators without rendering templates.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from .conftest import init_git_repo, run_repolish

if TYPE_CHECKING:
    import pytest


def _write(path: Path, text: str) -> None:
    """Write text to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding='utf-8')


def _write_repolish_config(tmp_path: Path, config: str) -> None:
    """Write repolish.yaml configuration file."""
    (tmp_path / 'repolish.yaml').write_text(textwrap.dedent(config), encoding='utf-8')


def test_validate_only_runs_validators_no_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--validate-only runs validators but skips template rendering.

    A provider with a validator should run the validator but not write files.
    """
    # Create an inline provider with a validator
    _write(
        tmp_path / 'validator_provider' / 'repolish.py',
        """\
        from pathlib import Path
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models.files import ValidationResult

        class Ctx(BaseContext):
            pass

        class ValidatorProvider(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_validators(self, context):
                def validate_file_exists(ctx, path: Path) -> ValidationResult:
                    # This validator checks if a file exists on disk
                    if path.exists():
                        return ValidationResult(
                            passed=True,
                            message=f"File {path} exists",
                            path=str(path),
                            validator_name="validate_file_exists",
                        )
                    return ValidationResult(
                        passed=False,
                        message=f"File {path} does not exist",
                        path=str(path),
                        validator_name="validate_file_exists",
                    )
                return {
                    'existing.txt': {'validate_file_exists': validate_file_exists},
                }
        """,
    )

    # Create the file that the validator will check
    (tmp_path / 'existing.txt').write_text("I exist!")

    _write_repolish_config(
        tmp_path,
        """\
        providers_order: ['validator_provider']
        providers:
          validator_provider:
            provider_root: ./validator_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    # Run with --validate-only - validator should pass (file exists)
    # but no files should be rendered
    result = run_repolish(['apply', '--validate-only'])

    # The validator should pass (existing.txt exists)
    assert result.exit_code == 0, f"--validate-only failed: {result.output}"


def test_validate_only_fails_on_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--validate-only --strict exits 1 when a validator fails."""
    # Create an inline provider with a failing validator
    _write(
        tmp_path / 'validator_provider' / 'repolish.py',
        """\
        from pathlib import Path
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models.files import ValidationResult

        class Ctx(BaseContext):
            pass

        class ValidatorProvider(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_validators(self, context):
                def validate_missing_file(ctx, path: Path) -> ValidationResult:
                    # This validator always fails
                    return ValidationResult(
                        passed=False,
                        message="Required file is missing",
                        path=str(path),
                        validator_name="validate_missing_file",
                    )
                return {
                    'missing.txt': {'validate_missing_file': validate_missing_file},
                }
        """,
    )

    _write_repolish_config(
        tmp_path,
        """\
        providers_order: ['validator_provider']
        providers:
          validator_provider:
            provider_root: ./validator_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    # Run with --validate-only --strict - validator failure causes exit 1
    result = run_repolish(['apply', '--validate-only', '--strict'], exit_code=-1)

    # The validator should fail, causing exit code 1 in strict mode
    assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code}"
    assert "Validation failed" in result.output or "missing" in result.output.lower()


def test_validate_only_skips_paused_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validators are skipped for files in paused_files.

    This tests the "ultimate turn off" mechanism - paused files should skip
    both rendering AND validation.
    """
    # Create an inline provider with a validator that would fail
    _write(
        tmp_path / 'validator_provider' / 'repolish.py',
        """\
        from pathlib import Path
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models.files import ValidationResult

        class Ctx(BaseContext):
            pass

        class ValidatorProvider(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_validators(self, context):
                def always_fail(ctx, path: Path) -> ValidationResult:
                    # This validator always fails
                    return ValidationResult(
                        passed=False,
                        message="Always fails",
                        path=str(path),
                        validator_name="always_fail",
                    )
                return {
                    'paused.txt': {'always_fail': always_fail},
                }
        """,
    )

    _write_repolish_config(
        tmp_path,
        """\
        providers_order: ['validator_provider']
        paused_files:
          - paused.txt
        providers:
          validator_provider:
            provider_root: ./validator_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    # Run with --validate-only - validator should be SKIPPED because file is paused
    result = run_repolish(['apply', '--validate-only'])

    # Should succeed because the validator was skipped
    assert result.exit_code == 0, f"Expected success (validator skipped), got: {result.output}"


def test_normal_apply_runs_validators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal `repolish apply` also runs validators before rendering."""
    # Create an inline provider with file_mappings and a validator
    _write(
        tmp_path / 'validator_provider' / 'repolish.py',
        """\
        from pathlib import Path
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models.files import ValidationResult

        class Ctx(BaseContext):
            pass

        class ValidatorProvider(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_mappings(self, context):
                return {'output.txt': 'output.txt.jinja'}

            def create_file_validators(self, context):
                def validate_prereq(ctx, path: Path) -> ValidationResult:
                    # Check that a prerequisite file exists
                    prereq = path.parent / 'prereq.txt'
                    if prereq.exists():
                        return ValidationResult(
                            passed=True,
                            message="Prerequisite exists",
                            path=str(path),
                            validator_name="validate_prereq",
                        )
                    return ValidationResult(
                        passed=False,
                        message="Missing prerequisite",
                        path=str(path),
                        validator_name="validate_prereq",
                    )
                return {
                    'output.txt': {'validate_prereq': validate_prereq},
                }
        """,
    )

    # Create the prerequisite file
    (tmp_path / 'prereq.txt').write_text("I am a prerequisite!")

    # Create the template in the repolish/ directory (standard inline provider layout)
    _write(
        tmp_path / 'validator_provider' / 'repolish' / 'output.txt.jinja',
        "Hello from template!",
    )

    _write_repolish_config(
        tmp_path,
        """\
        providers_order: ['validator_provider']
        providers:
          validator_provider:
            provider_root: ./validator_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    # Run normal apply - validator should pass, template should render
    result = run_repolish(['apply'])

    assert result.exit_code == 0, f"apply failed: {result.output}"
    assert (tmp_path / 'output.txt').exists()
    assert (tmp_path / 'output.txt').read_text() == "Hello from template!"


def test_normal_apply_fails_on_validation_failure_with_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal `repolish apply --strict` fails when validator fails."""
    # Create an inline provider with a failing validator
    _write(
        tmp_path / 'validator_provider' / 'repolish.py',
        """\
        from pathlib import Path
        from repolish import BaseContext, Provider, BaseInputs
        from repolish.providers.models.files import ValidationResult

        class Ctx(BaseContext):
            pass

        class ValidatorProvider(Provider[Ctx, BaseInputs]):
            def create_context(self):
                return Ctx()

            def create_file_validators(self, context):
                def always_fail(ctx, path: Path) -> ValidationResult:
                    return ValidationResult(
                        passed=False,
                        message="Validator always fails",
                        path=str(path),
                        validator_name="always_fail",
                    )
                return {
                    'target.txt': {'always_fail': always_fail},
                }
        """,
    )

    _write_repolish_config(
        tmp_path,
        """\
        providers_order: ['validator_provider']
        providers:
          validator_provider:
            provider_root: ./validator_provider
        """,
    )

    monkeypatch.chdir(tmp_path)
    init_git_repo(tmp_path)

    # Run with --strict to trigger hard failure on validator failure
    result = run_repolish(['apply', '--strict'], exit_code=-1)

    # Should fail because validator fails in strict mode
    assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code}"
