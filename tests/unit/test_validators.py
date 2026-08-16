"""Unit tests for file validator execution."""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from repolish.commands.apply.validators import run_validators
from repolish.config.models.provider import ProviderOverrides
from repolish.providers.contributions import _apply_validator_overrides
from repolish.providers.models import BaseContext, SessionBundle
from repolish.providers.models.files import (
    Accumulators,
    FileValidatorOptions,
    FileValidatorSpec,
    ValidationResult,
    ValidationStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestRunValidators:
    """Tests for the run_validators function."""

    def test_file_validator_spec_model_accepts_factory_shape(self) -> None:
        """The typed validator spec describes the provider API exactly."""

        def validator(
            context: BaseContext | None,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.PASS,
                message='ok',
                path=str(path),
                validator_name='lint',
            )

        spec = FileValidatorSpec(
            fn=validator,
            options=FileValidatorOptions(enabled=True),
        )

        assert spec.fn is validator
        assert spec.options.enabled is True

    def test_no_validators_returns_success(self, tmp_path: 'Path') -> None:
        """When no validators are provided, returns success."""
        bundle = MagicMock(spec=SessionBundle)
        bundle.file_validators = {}
        bundle.provider_contexts = {}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is True
        assert messages == []

    def test_validator_passes(self, tmp_path: 'Path') -> None:
        """A passing validator returns success."""
        # Create a test file
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test content')

        # Create a passing validator
        def passing_validator(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.PASS,
                message='Validation passed',
                path=str(path),
                validator_name='passing_validator',
            )

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test.txt': {'passing_validator': passing_validator},
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is True
        assert messages == []

    def test_validator_fails(self, tmp_path: 'Path') -> None:
        """A failing validator returns failure with message."""
        # Create a test file
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test content')

        # Create a failing validator
        def failing_validator(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.ERROR,
                message='Missing required content',
                path=str(path),
                validator_name='failing_validator',
            )

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test.txt': {'failing_validator': failing_validator},
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is False
        assert len(messages) == 1
        assert 'Missing required content' in messages[0]

    def test_validator_crash_handled(self, tmp_path: 'Path') -> None:
        """A validator that crashes is handled gracefully."""
        # Create a test file
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test content')

        # Create a crashing validator
        crash_message = 'Validator crashed!'

        def crashing_validator(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            raise RuntimeError(crash_message)

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test.txt': {'crashing_validator': crashing_validator},
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is False
        assert len(messages) == 1
        assert 'crashed' in messages[0]

    def test_disabled_validator_spec_is_skipped(self, tmp_path: 'Path') -> None:
        """A disabled FileValidatorSpec is not executed."""
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test content')

        def disabled_validator(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.ERROR,
                message='should not run',
                path=str(path),
                validator_name='disabled_validator',
            )

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test.txt': {
                'disabled_validator': FileValidatorSpec(
                    fn=disabled_validator,
                    options=FileValidatorOptions(enabled=False),
                ),
            },
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is True
        assert messages == []

    def test_validator_without_message_reports_generic_failure(
        self,
        tmp_path: 'Path',
    ) -> None:
        """A validator with no message is reported as a generic failure."""
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test content')

        def failing_without_message(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.ERROR,
                message='',
                path=str(path),
                validator_name='missing_message',
            )

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test.txt': {'missing_message': failing_without_message},
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is False
        assert len(messages) == 1
        assert 'missing_message' in messages[0]
        assert 'failed.' in messages[0]

    def test_warning_status_counts_as_failure(self, tmp_path: 'Path') -> None:
        """Warnings are explicit non-pass statuses and should fail the validator run."""
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test content')

        def warning_validator(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.WARNING,
                message='deprecated config',
                path=str(path),
                validator_name='warning_validator',
            )

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test.txt': {'warning_validator': warning_validator},
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is False
        assert len(messages) == 1
        assert 'deprecated config' in messages[0]

    def test_config_overrides_disable_validator_entry(self) -> None:
        """A config override keeps the validator in the registry but disables execution."""

        def lint(
            context: BaseContext | None,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.PASS,
                message='ok',
                path=str(path),
                validator_name='lint',
            )

        accum = Accumulators()
        accum.file_validators = {
            'config.toml': {'lint': lint},
        }

        _apply_validator_overrides(
            ProviderOverrides(validators={'config.toml': {'lint': False}}),
            accum,
        )

        entry = accum.file_validators['config.toml']['lint']
        assert isinstance(entry, FileValidatorSpec)
        assert entry.options.enabled is False
        assert entry.fn is lint

    def test_provider_disabled_validator_can_be_reenabled_by_config(
        self,
    ) -> None:
        """Provider defaults may be overridden by an explicit config opt-in."""

        def lint(
            context: BaseContext | None,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.PASS,
                message='ok',
                path=str(path),
                validator_name='lint',
            )

        accum = Accumulators()
        accum.file_validators = {
            'config.toml': {
                'lint': FileValidatorSpec(
                    fn=lint,
                    options=FileValidatorOptions(enabled=False),
                ),
            },
        }

        _apply_validator_overrides(
            ProviderOverrides(validators={'config.toml': {'lint': True}}),
            accum,
        )

        entry = accum.file_validators['config.toml']['lint']
        assert isinstance(entry, FileValidatorSpec)
        assert entry.options.enabled is True
        assert entry.fn is lint

    def test_all_validators_run(self, tmp_path: 'Path') -> None:
        """All validators run even when some fail."""
        # Create test files
        test_file1 = tmp_path / 'test1.txt'
        test_file1.write_text('test content 1')
        test_file2 = tmp_path / 'test2.txt'
        test_file2.write_text('test content 2')

        # Create failing validators
        def failing_validator_1(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.ERROR,
                message='Failed validator 1',
                path=str(path),
                validator_name='failing_validator_1',
            )

        def failing_validator_2(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.ERROR,
                message='Failed validator 2',
                path=str(path),
                validator_name='failing_validator_2',
            )

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test1.txt': {'failing_validator_1': failing_validator_1},
            'test2.txt': {'failing_validator_2': failing_validator_2},
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        # All validators should run
        assert all_passed is False
        assert len(messages) == 2

    def test_multiple_validators_same_file(self, tmp_path: 'Path') -> None:
        """Multiple validators for the same file all run."""
        # Create a test file
        test_file = tmp_path / 'test.txt'
        test_file.write_text('test content')

        # Create validators
        def passing_validator(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.PASS,
                message='Passed',
                path=str(path),
                validator_name='passing_validator',
            )

        def failing_validator(
            context: BaseContext,
            path: 'Path',
        ) -> ValidationResult:
            return ValidationResult(
                status=ValidationStatus.ERROR,
                message='Failed',
                path=str(path),
                validator_name='failing_validator',
            )

        bundle = MagicMock(spec=SessionBundle)
        bundle.paused_files = set()
        bundle.file_validators = {
            'test.txt': {
                'passing_validator': passing_validator,
                'failing_validator': failing_validator,
            },
        }
        bundle.provider_contexts = {'test': MagicMock()}

        all_passed, messages = run_validators(bundle, tmp_path)

        assert all_passed is False
        assert len(messages) == 1  # Only the failing one produces a message
