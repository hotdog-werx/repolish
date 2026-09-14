"""Validator report models and report-file writing.

Mirrors the insertion report pattern in
:mod:`repolish.insertions.reports`: every validated file gets a JSON report
under ``.repolish/_/validators/`` recording what ran, what passed, what was
disabled, and — when a validator raised — the stack trace as a list of lines.
The summary tree links to the report so failures can be debugged without
re-running with a debugger attached.
"""

from __future__ import annotations

import json
import traceback
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from repolish.commands.apply.validators import ValidatorOutcome


def traceback_lines(exc: BaseException) -> list[str]:
    """Return the full traceback of *exc* as a list of lines."""
    return ''.join(
        traceback.format_exception(type(exc), exc, exc.__traceback__),
    ).splitlines()


class ValidatorReportEntry(BaseModel):
    """Outcome of a single registered validator for one file."""

    kind: Literal['validator', 'disabled'] = 'validator'
    name: str = Field(..., description='The validator name')
    status: str = Field(..., description='pass, warning, error, or disabled')
    message: str = Field(default='', description='Failure or disable message')
    traceback: list[str] | None = Field(
        default=None,
        description='Stack trace lines when the validator raised',
    )

    @classmethod
    def from_outcome(cls, outcome: ValidatorOutcome) -> ValidatorReportEntry:
        """Build an entry from a single validator execution outcome."""
        return cls(
            name=outcome.name,
            status=outcome.status.value,
            message=outcome.message or '',
            traceback=outcome.traceback,
        )

    @classmethod
    def disabled(cls, name: str) -> ValidatorReportEntry:
        """Build an entry for a validator skipped because it is disabled."""
        return cls(kind='disabled', name=name, status='disabled')


class ValidatorReport(BaseModel):
    """Complete validator report for one file."""

    file: str = Field(..., description='Relative path of the file')
    provider_alias: str = Field(
        default='',
        description='Alias of the provider that declared the validators',
    )
    total_validators: int = Field(
        default=0,
        ge=0,
        description='Validators registered for the file (enabled or not)',
    )
    failed: int = Field(
        default=0,
        ge=0,
        description='Entries with error status',
    )
    warnings: int = Field(
        default=0,
        ge=0,
        description='Entries with warning status',
    )
    disabled: int = Field(
        default=0,
        ge=0,
        description='Entries disabled before running',
    )
    entries: list[ValidatorReportEntry] = Field(
        default_factory=list,
        description='All diagnostic entries in registration order',
    )


def write_validator_report(
    reports_dir: Path,
    rel_path: str,
    provider_alias: str,
    entries: Iterable[ValidatorReportEntry],
    total_validators: int,
) -> str:
    """Write the report for one file and return its POSIX path.

    The filename mirrors the insertion reports (``validators.<slug>.<alias>.json``)
    so both report families sit side by side under ``.repolish/_``.
    """
    entries_list = list(entries)
    report = ValidatorReport(
        file=rel_path,
        provider_alias=provider_alias,
        total_validators=total_validators,
        failed=sum(1 for e in entries_list if e.status == 'error'),
        warnings=sum(1 for e in entries_list if e.status == 'warning'),
        disabled=sum(1 for e in entries_list if e.kind == 'disabled'),
        entries=entries_list,
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f'validators.{_slug(rel_path)}.{provider_alias}.json'
    report_file.write_text(
        json.dumps(report.model_dump(), indent=2),
        encoding='utf-8',
    )
    return report_file.as_posix()


def _slug(rel_path: str) -> str:
    """Return the same filename slug used by the debug file writers."""
    from repolish.utils import path_slug  # noqa: PLC0415

    return path_slug(rel_path)
