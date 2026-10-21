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


HOOK_SKIP_SEMANTICS: dict[str, str] = {
    'create_context': 'the provider is left with an empty context',
    'provide_inputs': 'the provider is treated as emitting no inputs',
    'finalize_context': 'the provider keeps its pre-finalize context',
    'promote_file_mappings': 'the provider declares no promoted mappings',
    'create_file_mappings': 'the provider contributes no file mappings',
    'create_file_validators': 'the provider declares no validators',
    'create_file_insertions': 'the provider declares no insertion functions',
    'create_fast_lanes': 'the provider declares no fast lanes',
    'create_spec': 'the facet contributes no spec, so its file goes unmanaged',
    'create_anchors': 'the provider declares no anchors',
}
"""What a run is left with when each guarded hook fails, in pipeline order.

`record()` rejects a hook name missing from this table, so a new capture
site must document its skip semantics here at the same time. The local
provider renders the provider docs' behaviour table from this registry.
"""


class HookFailure(BaseModel):
    """One provider or facet hook exception caught during the pipeline.

    The provider keeps working with the hook skipped; this record is what
    the summary tree shows and what the debug report in ``.repolish/_``
    is written from.
    """

    provider_id: str = Field(
        description='Loader provider id (the posix provider root path).',
    )
    alias: str = Field(
        default='',
        description='Configured provider alias at capture time (falls back to provider_id).',
    )
    facet_name: str | None = Field(
        default=None,
        description='Facet name when the failing hook belongs to a facet.',
    )
    hook: str = Field(
        description=(
            'Hook name, e.g. `create_context`, `finalize_context`, '
            '`create_spec`; must be registered in `HOOK_SKIP_SEMANTICS`.'
        ),
    )
    error: str = Field(description='`str(exc)` of the caught exception.')
    traceback: list[str] = Field(
        default_factory=list,
        description='Full traceback lines, written verbatim into the debug report.',
    )
    report_path: str | None = Field(
        default=None,
        description='Debug-report path once the apply session has written it.',
    )


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
        if hook not in HOOK_SKIP_SEMANTICS:
            msg = (
                f'unknown hook {hook!r}: register its skip semantics in HOOK_SKIP_SEMANTICS alongside the capture site'
            )
            raise ValueError(msg)
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
