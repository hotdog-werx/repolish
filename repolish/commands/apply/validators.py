"""Validation helpers for file validators contributed by providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from repolish.providers.models.files import (
    FileValidatorEntry,
    FileValidatorSpec,
    ValidationResult,
    ValidatorFn,
)

if TYPE_CHECKING:
    from pathlib import Path

    from repolish.providers.models import BaseContext, SessionBundle


def _resolve_mapping_validator(value: dict[str, object]) -> ValidatorFn | None:
    """Resolve a validator from a dict-shaped registration payload."""
    for key in ('fn', 'validator', 'callable'):
        candidate = value.get(key)
        if callable(candidate):
            return cast('ValidatorFn', candidate)
    return None


def _resolve_validator(value: FileValidatorEntry) -> ValidatorFn | None:
    """Return a callable validator from a provider registration."""
    if isinstance(value, FileValidatorSpec):
        return value.fn
    if callable(value):
        return cast('ValidatorFn', value)
    if isinstance(value, dict):
        return _resolve_mapping_validator(value)
    return None


def _validator_outcome(
    validation: ValidationResult,
    validator_name: str,
) -> tuple[bool, str, str]:
    """Normalize a validator result into success state and display details."""
    return (
        validation.passed,
        validation.message,
        validation.validator_name or validator_name,
    )


def _run_single_validator(
    validator_name: str,
    rel_path: str,
    validator_entry: FileValidatorEntry,
    provider_contexts: dict[str, BaseContext],
    project_root: Path,
) -> tuple[bool, list[str]]:
    """Execute one validator and return success plus any messages."""
    validator = _resolve_validator(validator_entry)
    if validator is None:
        return False, [
            f"Validator '{validator_name}' for '{rel_path}' could not be loaded.",
        ]

    context = next(iter(provider_contexts.values()), None)
    try:
        validation = validator(context, project_root / rel_path)
    except Exception as exc:  # noqa: BLE001 - validation failures are surfaced to users
        return False, [
            f"Validator '{validator_name}' for '{rel_path}' crashed: {exc}",
        ]

    passed, message, display_name = _validator_outcome(
        validation,
        validator_name,
    )
    if passed:
        return True, []
    if message:
        return False, [f"{display_name} for '{rel_path}': {message}"]
    return False, [f"Validator '{display_name}' failed for '{rel_path}'."]


def _run_validators_for_file(
    rel_path: str,
    validators: dict[str, FileValidatorEntry],
    provider_contexts: dict[str, BaseContext],
    project_root: Path,
) -> tuple[bool, list[str]]:
    """Execute all validators registered for one destination file."""
    result = True
    messages: list[str] = []

    for validator_name, validator_entry in validators.items():
        validator_ok, validator_messages = _run_single_validator(
            validator_name,
            rel_path,
            validator_entry,
            provider_contexts,
            project_root,
        )
        if not validator_ok:
            result = False
        messages.extend(validator_messages)

    return result, messages


def run_validators(
    bundle: SessionBundle,
    project_root: Path,
) -> tuple[bool, list[str]]:
    """Execute all registered file validators for this session."""
    result = True
    messages: list[str] = []
    validators_by_file = bundle.file_validators
    provider_contexts = bundle.provider_contexts

    for rel_path, validators in validators_by_file.items():
        if not isinstance(validators, dict):
            continue
        file_ok, file_messages = _run_validators_for_file(
            rel_path,
            validators,
            provider_contexts,
            project_root,
        )
        if not file_ok:
            result = False
        messages.extend(file_messages)

    return result, messages
