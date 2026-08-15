"""Validation helpers for file validators contributed by providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from repolish.providers.models import BaseContext, SessionBundle
from repolish.providers.models.files import (
    FileValidatorEntry,
    FileValidatorSpec,
    ValidationResult,
    ValidationStatus,
    ValidatorFn,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _resolve_validator(value: FileValidatorEntry) -> ValidatorFn:
    """Return a callable validator from a provider registration."""
    if isinstance(value, FileValidatorSpec):
        return value.fn
    return value


def _validator_outcome(
    validation: ValidationResult,
    validator_name: str,
) -> tuple[ValidationStatus, str, str]:
    """Normalize a validator result into status state and display details."""
    return (
        validation.status,
        validation.message,
        validation.validator_name or validator_name,
    )


def _validator_entry_enabled(entry: FileValidatorEntry) -> bool:
    """Return whether a validator entry is enabled after config overrides."""
    if isinstance(entry, FileValidatorSpec):
        return entry.options.enabled
    return True


def _resolve_validation_path(
    rel_path: str,
    workspace_root: Path,
    render_root: Path | None = None,
) -> Path:
    """Resolve the file to validate.

    Prefer the real workspace file when it exists, because providers may validate
    an already-present project file without any render mapping. Fall back to the
    rendered staging directory for generated files that do not exist yet in the
    project tree.
    """
    for root in (workspace_root, render_root):
        if root:
            candidate = root / rel_path
            if candidate.exists():
                return candidate
    return workspace_root / rel_path


def _run_single_validator(  # noqa: PLR0913 - private helper
    validator_name: str,
    rel_path: str,
    validator_entry: FileValidatorEntry,
    provider_contexts: dict[str, BaseContext],
    workspace_root: Path,
    render_root: Path | None = None,
) -> tuple[ValidationStatus, str | None]:
    """Execute one validator and return its normalized status plus a reason."""
    validator = _resolve_validator(validator_entry)
    context = next(iter(provider_contexts.values()), BaseContext())
    resolved_path = _resolve_validation_path(
        rel_path,
        workspace_root,
        render_root,
    )
    try:
        validation = cast('Callable[[BaseContext, Path], ValidationResult]', validator)(
            context,
            resolved_path,
        )
    except Exception as exc:  # noqa: BLE001 - validation failures are surfaced to users
        return (
            ValidationStatus.ERROR,
            f'Validator {validator_name!r} for {rel_path!r} crashed: {exc}',
        )

    status, message, _display_name = _validator_outcome(
        validation,
        validator_name,
    )
    if status == ValidationStatus.PASS:
        return ValidationStatus.PASS, None
    if message:
        return status, message
    return status, 'failed.'


def _run_validators_for_file(
    rel_path: str,
    validators: dict[str, FileValidatorEntry],
    provider_contexts: dict[str, BaseContext],
    workspace_root: Path,
    render_root: Path | None = None,
) -> tuple[bool, dict[str, ValidationResult]]:
    """Execute all validators registered for one destination file."""
    result = True
    outcomes: dict[str, ValidationResult] = {}

    for validator_name, validator_entry in validators.items():
        if not _validator_entry_enabled(validator_entry):
            continue
        status, failure_message = _run_single_validator(
            validator_name,
            rel_path,
            validator_entry,
            provider_contexts,
            workspace_root,
            render_root,
        )
        if status != ValidationStatus.PASS:
            result = False
            if failure_message is not None:
                outcomes[validator_name] = ValidationResult(
                    status=status,
                    message=failure_message,
                    path=rel_path,
                    validator_name=validator_name,
                )

    return result, outcomes


def _collect_file_validation_messages(
    bundle: SessionBundle,
    workspace_root: Path,
    render_root: Path | None = None,
) -> dict[str, dict[str, ValidationResult]]:
    """Execute all validators and return per-file per-validator status details."""
    failures: dict[str, dict[str, ValidationResult]] = {}
    validators_by_file = bundle.file_validators
    provider_contexts = bundle.provider_contexts

    for rel_path, validators in validators_by_file.items():
        file_ok, file_results = _run_validators_for_file(
            rel_path,
            validators,
            provider_contexts,
            workspace_root,
            render_root,
        )
        if not file_ok:
            failures[rel_path] = file_results

    return failures


def run_validators(
    bundle: SessionBundle,
    project_root: Path,
) -> tuple[bool, list[str]]:
    """Execute all registered file validators for this session."""
    failures = _collect_file_validation_messages(bundle, project_root)
    all_passed = not any(
        result.status != ValidationStatus.PASS for by_name in failures.values() for result in by_name.values()
    )
    messages = [
        f'{path}: {name}: {result.message}' for path, by_name in failures.items() for name, result in by_name.items()
    ]
    return all_passed, messages
