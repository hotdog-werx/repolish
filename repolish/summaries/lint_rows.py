"""Derivation for the lint report: template results in, rows out.

`repolish lint` hands its finished analysis (one `TemplateResult` per
template) to `lint_template_rows` and gets one `LintTemplateRow` per
template with its `LintState` and findings; `unmapped_source_rows` maps
the never-referenced conditional sources. Rendering lives in
`repolish.reporting.leaves`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repolish.summaries.rows import (
    LintIssueRow,
    LintState,
    LintTemplateRow,
    UnmappedSourceRow,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from repolish.summaries.contract import TemplateResult


def lint_template_rows(
    results: Sequence[TemplateResult],
) -> list[LintTemplateRow]:
    """Turn one provider's template results into lint rows, in order.

    A template is OK when it rendered cleanly and has no issues; warnings
    are carried as plain strings and never fail it.
    """
    return [
        LintTemplateRow(
            path=result.path,
            state=(LintState.OK if result.render_error is None and not result.issues else LintState.FAILED),
            issues=tuple(LintIssueRow(chain=issue.chain, reason=issue.reason) for issue in result.issues),
            warnings=tuple(result.warnings),
            render_error=result.render_error,
        )
        for result in results
    ]


def unmapped_source_rows(
    unmapped: Sequence[tuple[str, str]],
) -> list[UnmappedSourceRow]:
    """Map the never-referenced (alias, path) pairs to path rows, in order."""
    return [UnmappedSourceRow(path=path) for _, path in unmapped]
