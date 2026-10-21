"""Hook-failure records for the provider pipeline.

A provider or facet hook that raises is never fatal: the pipeline catches
the exception, records a `HookFailure` here, and skips that hook so the
run continues. The collected failures travel on the `SessionBundle` to the
apply session, which writes the debug reports and renders the summary rows.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


def traceback_lines(exc: BaseException) -> list[str]:
    """Return the full traceback of *exc* as a list of text lines."""
    return list(traceback.format_exception(exc))


class HookFailure(BaseModel):
    """One provider or facet hook exception caught during the pipeline.

    The provider keeps working with the hook skipped; this record is what
    the summary tree shows and what the debug report in ``.repolish/_``
    is written from.
    """

    provider_id: str
    """Loader provider id (the posix provider root path)."""
    alias: str = ''
    """Configured provider alias at capture time (falls back to provider_id)."""
    facet_name: str | None = None
    """Facet name when the failing hook belongs to a facet."""
    hook: str
    """Hook name, e.g. ``create_context``, ``finalize_context``, ``create_spec``."""
    error: str
    """``str(exc)`` of the caught exception."""
    traceback: list[str] = Field(default_factory=list)
    """Full traceback lines, written verbatim into the debug report."""
    report_path: str | None = None
    """Debug-report path once the apply session has written it."""


@dataclass
class HookFailureCollector:
    """Mutable accumulator the pipeline records hook failures into."""

    failures: list[HookFailure] = field(default_factory=list)

    def record(
        self,
        *,
        provider_id: str,
        hook: str,
        exc: BaseException,
        alias: str = '',
        facet_name: str | None = None,
    ) -> None:
        """Append one failure record; the traceback is captured here."""
        self.failures.append(
            HookFailure(
                provider_id=provider_id,
                alias=alias or provider_id,
                facet_name=facet_name,
                hook=hook,
                error=str(exc),
                traceback=traceback_lines(exc),
            ),
        )
