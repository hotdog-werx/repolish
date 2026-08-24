"""Insertion report generation and formatting.

This module provides Pydantic models for insertion reports, making them:
- Type-safe and self-documenting
- Easy to serialize/deserialize via model_dump()
- Validated at construction time

Reports are written per-provider per-file and include:
- Error diagnostics (parse failures, renderer exceptions)
- Disabled block entries (config overrides)
- Summary statistics (total blocks, failed blocks, disabled blocks)
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from repolish.insertions.disabled import DisabledInsertionEntry
    from repolish.insertions.writer import WriteDiagnostic


class ErrorDiagnosticEntry(BaseModel):
    """A single error diagnostic in a report."""

    kind: Literal['error'] = 'error'
    tag: str = Field(..., description='The insertion block tag')
    message: str = Field(..., description='Error message')
    traceback: list[str] | None = Field(
        default=None,
        description='Stack trace lines if an exception occurred',
    )

    @classmethod
    def from_diagnostic(cls, diag: WriteDiagnostic) -> ErrorDiagnosticEntry:
        """Build an entry from a WriteDiagnostic object."""
        trace_lines: list[str] | None = None
        if diag.exception is not None:
            trace_text = ''.join(
                traceback.format_exception(
                    type(diag.exception),
                    diag.exception,
                    diag.exception.__traceback__,
                ),
            )
            trace_lines = trace_text.splitlines()

        return cls(
            tag=diag.tag,
            message=diag.message,
            traceback=trace_lines,
        )


class DisabledDiagnosticEntry(BaseModel):
    """A single disabled block entry in a report."""

    kind: Literal['disabled'] = 'disabled'
    tag: str = Field(..., description='The insertion block tag')
    function: str = Field(..., description='The function name')
    message: str = Field(..., description='Reason for disable')
    traceback: None = None

    @classmethod
    def from_entry(
        cls,
        entry: DisabledInsertionEntry,
    ) -> DisabledDiagnosticEntry:
        """Build an entry from a DisabledInsertionEntry."""
        return cls(
            tag=entry.tag,
            function=entry.function,
            message=entry.message,
        )


class InsertionReport(BaseModel):
    """Complete insertion report for a file/provider combination."""

    file: str = Field(..., description='Relative path of the file')
    source_provider: str = Field(
        ...,
        description='Provider ID that owns the file',
    )
    provider_alias: str = Field(..., description='Provider alias for display')
    total_blocks: int = Field(
        ...,
        ge=0,
        description='Total insertion blocks found',
    )
    failed_blocks: int = Field(
        ...,
        ge=0,
        description='Blocks that failed to render',
    )
    disabled_blocks: int = Field(
        ...,
        ge=0,
        description='Blocks disabled by config',
    )
    functions: list[str] = Field(
        default_factory=list,
        description='Function names that were called',
    )
    diagnostics: list[ErrorDiagnosticEntry | DisabledDiagnosticEntry] = Field(
        default_factory=list,
        description='All diagnostic entries (errors + disabled)',
    )
