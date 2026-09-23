"""Derivation tests for the lint report: template results in, rows out.

Every test hand-builds `TemplateResult` contract data (the concrete
dataclass `repolish lint` constructs) and asserts the lint rows: state
per template, issue rows, and the unmapped-source mapping.
"""

from repolish.summaries import lint_template_rows, unmapped_source_rows
from repolish.summaries.contract import LintIssue, TemplateResult
from repolish.summaries.rows import (
    LintIssueRow,
    LintState,
    LintTemplateRow,
    UnmappedSourceRow,
)


def test_clean_template_is_ok() -> None:
    (row,) = lint_template_rows([TemplateResult(path='a.md')])
    assert row.state is LintState.OK
    assert row.issues == ()
    assert row.warnings == ()
    assert row.render_error is None


def test_warnings_do_not_fail_a_template() -> None:
    result = TemplateResult(
        path='a.md',
        warnings=("insert zone 'b': brand it",),
    )
    (row,) = lint_template_rows([result])
    assert row.state is LintState.OK
    assert row.warnings == ("insert zone 'b': brand it",)


def test_issues_fail_a_template() -> None:
    result = TemplateResult(
        path='a.md',
        issues=(
            LintIssue(
                template='a.md',
                chain='x.y',
                reason="'x' not in context",
            ),
        ),
    )
    (row,) = lint_template_rows([result])
    assert row.state is LintState.FAILED
    assert row.issues == (LintIssueRow(chain='x.y', reason="'x' not in context"),)


def test_render_error_fails_a_template() -> None:
    result = TemplateResult(path='a.md', render_error='syntax error: nope')
    (row,) = lint_template_rows([result])
    assert row.state is LintState.FAILED
    assert row.render_error == 'syntax error: nope'


def test_findings_keep_template_order() -> None:
    results = [
        TemplateResult(path='b.md', render_error='boom'),
        TemplateResult(path='a.md'),
        TemplateResult(path='c.md', warnings=('advisory',)),
    ]
    rows = lint_template_rows(results)
    assert [row.path for row in rows] == ['b.md', 'a.md', 'c.md']
    assert [row.state for row in rows] == [
        LintState.FAILED,
        LintState.OK,
        LintState.OK,
    ]


def test_no_results_derive_no_rows() -> None:
    assert lint_template_rows([]) == []


def test_rows_are_frozen_row_data() -> None:
    result = TemplateResult(
        path='a.md',
        issues=(LintIssue(template='a.md', chain='x', reason='why'),),
    )
    (row,) = lint_template_rows([result])
    assert row == LintTemplateRow(
        path='a.md',
        state=LintState.FAILED,
        issues=row.issues,
    )


def test_unmapped_pairs_map_to_path_rows() -> None:
    rows = unmapped_source_rows([('alias', 'a.toml'), ('other', 'b.toml')])
    assert rows == [
        UnmappedSourceRow(path='a.toml'),
        UnmappedSourceRow(path='b.toml'),
    ]


def test_unmapped_alias_is_dropped() -> None:
    """The alias feeds the logger, not the display; the row carries the path."""
    (row,) = unmapped_source_rows([('some-alias', 'a.toml')])
    assert row == UnmappedSourceRow(path='a.toml')


def test_no_unmapped_sources_derive_no_rows() -> None:
    assert unmapped_source_rows([]) == []
