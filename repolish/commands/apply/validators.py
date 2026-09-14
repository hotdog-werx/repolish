"""Validation helpers for file validators contributed by providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from repolish.commands.apply.validator_reports import (
    ValidatorReportEntry,
    traceback_lines,
    write_validator_report,
)
from repolish.config.paused import is_paused
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


@dataclass(frozen=True)
class ValidatorOutcome:
    """Raw outcome of one validator execution, kept for report entries."""

    name: str
    status: ValidationStatus
    message: str | None
    traceback: list[str] | None = None


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
) -> ValidatorOutcome:
    """Execute one validator and return its raw outcome (status, reason, trace)."""
    validator = _resolve_validator(validator_entry)
    context = next(iter(provider_contexts.values()), BaseContext())
    resolved_path = _resolve_validation_path(
        rel_path,
        workspace_root,
        render_root,
    )
    try:
        validation = cast(
            'Callable[[BaseContext, Path], ValidationResult]',
            validator,
        )(
            context,
            resolved_path,
        )
    except Exception as exc:  # noqa: BLE001 - validation failures are surfaced to users
        return ValidatorOutcome(
            name=validator_name,
            status=ValidationStatus.ERROR,
            message=f'Validator {validator_name!r} for {rel_path!r} crashed: {exc}',
            traceback=traceback_lines(exc),
        )

    status, message, _display_name = _validator_outcome(
        validation,
        validator_name,
    )
    if status == ValidationStatus.PASS:
        return ValidatorOutcome(validator_name, status, None)
    if message:
        return ValidatorOutcome(validator_name, status, message)
    return ValidatorOutcome(validator_name, status, 'failed.')


def _run_validators_for_file(
    rel_path: str,
    validators: dict[str, FileValidatorEntry],
    provider_contexts: dict[str, BaseContext],
    workspace_root: Path,
    render_root: Path | None = None,
) -> tuple[bool, dict[str, ValidationResult], list[ValidatorReportEntry]]:
    """Execute all validators registered for one destination file.

    Returns whether the file passed, the per-validator *failure* results (the
    contract the summary tree and ``run_validators`` consume), and report
    entries for every registered validator — passes, failures, disables, and
    crash tracebacks alike.
    """
    result = True
    outcomes: dict[str, ValidationResult] = {}
    entries: list[ValidatorReportEntry] = []

    for validator_name, validator_entry in validators.items():
        if not _validator_entry_enabled(validator_entry):
            entries.append(ValidatorReportEntry.disabled(validator_name))
            continue
        outcome = _run_single_validator(
            validator_name,
            rel_path,
            validator_entry,
            provider_contexts,
            workspace_root,
            render_root,
        )
        entries.append(ValidatorReportEntry.from_outcome(outcome))
        if outcome.status != ValidationStatus.PASS:
            result = False
            if outcome.message is not None:
                outcomes[validator_name] = ValidationResult(
                    status=outcome.status,
                    message=outcome.message,
                    path=rel_path,
                    validator_name=validator_name,
                )

    return result, outcomes, entries


def _validator_alias(
    bundle: SessionBundle,
    rel_path: str,
    pid_to_alias: dict[str, str],
) -> str:
    """Return the alias of the provider that declared the file's validators."""
    pid = bundle.validator_sources.get(rel_path)
    return pid_to_alias.get(pid, pid) if pid else 'provider'


def _collect_validation(
    bundle: SessionBundle,
    workspace_root: Path,
    render_root: Path | None = None,
    *,
    reports_dir: Path | None = None,
    pid_to_alias: dict[str, str] | None = None,
) -> tuple[dict[str, dict[str, ValidationResult]], dict[str, str]]:
    """Execute all validators; return failures and per-file report paths.

    When *reports_dir* is given, every validated file also gets a JSON report
    written there (see :mod:`repolish.commands.apply.validator_reports`), and
    the second dict maps each file to that report's POSIX path.
    """
    failures: dict[str, dict[str, ValidationResult]] = {}
    report_paths: dict[str, str] = {}
    validators_by_file = bundle.file_validators
    provider_contexts = bundle.provider_contexts

    for rel_path, validators in validators_by_file.items():
        if is_paused(rel_path, bundle.paused_files):
            continue
        file_ok, file_results, entries = _run_validators_for_file(
            rel_path,
            validators,
            provider_contexts,
            workspace_root,
            render_root,
        )
        if not file_ok:
            failures[rel_path] = file_results
        if reports_dir is not None:
            report_paths[rel_path] = write_validator_report(
                reports_dir,
                rel_path,
                _validator_alias(bundle, rel_path, pid_to_alias or {}),
                entries,
                total_validators=len(validators),
            )

    return failures, report_paths


def _collect_file_validation_messages(
    bundle: SessionBundle,
    workspace_root: Path,
    render_root: Path | None = None,
) -> dict[str, dict[str, ValidationResult]]:
    """Execute all validators and return per-file per-validator status details."""
    return _collect_validation(bundle, workspace_root, render_root)[0]


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
