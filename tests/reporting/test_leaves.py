"""Unit tests for the leaf renderers: rows in, `SummaryNode` trees out.

Each test builds rows directly (no session construction) and asserts the
rendered text: glyph, note, stat suffix, and hyperlink treatment.
"""

from pathlib import Path

from pytest_mock import MockerFixture
from rich.style import Style

from repolish.reporting.leaves import (
    render_command_row,
    render_copy_row,
    render_file_row,
    render_insertion_catalog,
    render_lint_templates,
    render_post_process_group,
    render_promoted_row,
    render_provider_branch,
    render_session_group,
    render_session_groups,
    render_symlink_row,
    render_unmapped_sources,
)
from repolish.reporting.nodes import SummaryNode
from repolish.summaries.rows import (
    AppliedStats,
    CommandRow,
    CommandState,
    CopyRow,
    CopyState,
    FileRow,
    FileState,
    InsertionCatalogGroup,
    InsertionFunctionRow,
    InsertionLine,
    InsertionState,
    LintIssueRow,
    LintState,
    LintTemplateRow,
    PendingStats,
    PostProcessGroup,
    PromotedRow,
    PromotedState,
    ProviderBranch,
    SessionGroup,
    SymlinkRow,
    UnmappedSourceRow,
    ValidatorLine,
    ValidatorState,
)


def _styles(node: SummaryNode) -> set[str | Style]:
    return {span.style for span in node.label.spans}


# --- file rows -----------------------------------------------------------


def test_file_row_written_renders_green_check() -> None:
    node = render_file_row(FileRow(path='a.md', state=FileState.WRITTEN))
    assert node.label.plain == '✓ a.md'
    assert 'green' in _styles(node)


def test_file_row_unchanged_renders_tilde() -> None:
    node = render_file_row(FileRow(path='a.md', state=FileState.UNCHANGED))
    assert node.label.plain == '~ a.md'


def test_file_row_drift_renders_red_cross() -> None:
    node = render_file_row(FileRow(path='a.md', state=FileState.DRIFT))
    assert node.label.plain == '✗ a.md'
    assert 'red' in _styles(node)


def test_file_row_paused_shows_reason() -> None:
    node = render_file_row(FileRow(path='a.md', state=FileState.PAUSED))
    assert node.label.plain == '✗ a.md  paused'
    assert 'dim yellow' in _styles(node)


def test_file_row_suppressed_and_disabled_show_reasons() -> None:
    suppressed = render_file_row(
        FileRow(path='a.md', state=FileState.SUPPRESSED),
    )
    assert suppressed.label.plain == '✗ a.md  suppressed'
    disabled = render_file_row(FileRow(path='b.md', state=FileState.DISABLED))
    assert disabled.label.plain == '✗ b.md  disabled'


def test_file_row_root_skipped_shows_full_reason() -> None:
    node = render_file_row(FileRow(path='a.md', state=FileState.ROOT_SKIPPED))
    assert node.label.plain == '✗ a.md  not in create_file_mappings (root mode)'


def test_file_row_hollow_states_render_open_circle() -> None:
    insertion = render_file_row(
        FileRow(path='a.md', state=FileState.INSERTION_ONLY),
    )
    assert insertion.label.plain == '◌ a.md'
    validator = render_file_row(
        FileRow(path='b.md', state=FileState.VALIDATOR_ONLY),
    )
    assert validator.label.plain == '◌ b.md'


def test_file_row_renders_mode_source_and_owner_notes() -> None:
    row = FileRow(
        path='new.md',
        state=FileState.OK,
        source='_p/new.md',
        mode_note='create_only',
        owner_note='owned by p',
    )
    node = render_file_row(row)
    assert node.label.plain == '✓ new.md  create_only  ← _p/new.md  owned by p'
    assert 'dim yellow' in _styles(node)


def test_file_row_validator_lines_render_per_state() -> None:
    row = FileRow(
        path='x.md',
        state=FileState.OK,
        validators=(
            ValidatorLine(name='lint', state=ValidatorState.PASS),
            ValidatorLine(
                name='fmt',
                state=ValidatorState.WARNING,
                message='spacing',
            ),
            ValidatorLine(
                name='schema',
                state=ValidatorState.ERROR,
                message='bad',
            ),
            ValidatorLine(
                name='audit',
                state=ValidatorState.DISABLED,
                message='disabled',
            ),
        ),
    )
    node = render_file_row(row)
    assert '\n  validators:' in node.label.plain
    assert '\n    - ✓ lint' in node.label.plain  # a pass is the name alone
    assert '\n    - ⚠ fmt: spacing' in node.label.plain
    assert '\n    - ✗ schema: bad' in node.label.plain
    assert '\n    - ✗ audit: disabled' in node.label.plain


def test_file_row_validator_report_gets_details_link(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch('repolish.reporting.nodes.supports_hyperlinks', new=True)
    report = tmp_path / 'report.json'
    row = FileRow(
        path='x.md',
        state=FileState.OK,
        validators=(ValidatorLine(name='lint', state=ValidatorState.PASS),),
        validator_report=report,
    )
    node = render_file_row(row)
    assert node.label.plain.endswith(' [details]')
    assert any(str(report) in str(span.style) for span in node.label.spans)


def test_file_row_insertion_line_renders_counts_and_link(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch('repolish.reporting.nodes.supports_hyperlinks', new=True)
    report = tmp_path / 'insertion-report.json'
    row = FileRow(
        path='x.md',
        state=FileState.WRITTEN,
        insertion=InsertionLine(
            state=InsertionState.OK,
            succeeded=2,
            failed=1,
            disabled=1,
            link=report,
        ),
    )
    node = render_file_row(row)
    assert '\n  insertions: ✓ ok (2 ok, 1 failed, 1 disabled)' in node.label.plain
    assert any(str(report) in str(span.style) for span in node.label.spans)


def test_file_row_link_hyperlinks_the_path(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch('repolish.reporting.leaves.supports_hyperlinks', new=True)
    ctx = tmp_path / 'file-context.json'
    node = render_file_row(
        FileRow(path='a.md', state=FileState.WRITTEN, link=ctx),
    )
    assert any(f'link file://{ctx}' in str(span.style) for span in node.label.spans)


def test_file_row_link_without_hyperlink_support(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch('repolish.reporting.leaves.supports_hyperlinks', new=False)
    node = render_file_row(
        FileRow(path='a.md', state=FileState.WRITTEN, link=tmp_path / 'x.json'),
    )
    assert node.label.plain == '✓ a.md'


# --- symlinks and copies --------------------------------------------------


def test_symlink_row_renders_arrow_target_source() -> None:
    node = render_symlink_row(SymlinkRow(target='.venv', source='p/.venv'))
    assert node.label.plain == '↗ .venv  → p/.venv'
    assert 'blue' in _styles(node)


def test_copy_row_active_renders_plain_clipboard() -> None:
    node = render_copy_row(
        CopyRow(target='configs', source='p/configs', state=CopyState.ACTIVE),
    )
    assert node.label.plain == '📋 configs  ← p/configs'


def test_copy_row_paused_states_render_notes() -> None:
    paused = render_copy_row(
        CopyRow(target='configs', source='p/configs', state=CopyState.PAUSED),
    )
    assert paused.label.plain == '⏸ configs  ← p/configs (paused)'
    partial = render_copy_row(
        CopyRow(
            target='configs',
            source='p/configs',
            state=CopyState.PARTIALLY_PAUSED,
        ),
    )
    assert partial.label.plain == '◐ configs  ← p/configs (partially paused)'


# --- promoted rows ---------------------------------------------------------


def test_promoted_row_written_renders_promotion_note() -> None:
    row = PromotedRow(
        path='pkg.md',
        state=PromotedState.WRITTEN,
        promoted_from='pkg',
    )
    node = render_promoted_row(row)
    assert node.label.plain == '↑ pkg.md  promoted from pkg'


def test_promoted_row_unchanged_keeps_up_arrow() -> None:
    row = PromotedRow(
        path='pkg.md',
        state=PromotedState.UNCHANGED,
        promoted_from='pkg',
    )
    assert render_promoted_row(row).label.plain == '~ pkg.md  ↑ promoted from pkg'


def test_promoted_row_overridden_names_the_owner() -> None:
    row = PromotedRow(
        path='pkg.md',
        state=PromotedState.OVERRIDDEN_BY_ROOT,
        promoted_from='pkg',
    )
    node = render_promoted_row(row)
    assert node.label.plain == '↑ pkg.md  ⚠ overridden by root'
    row_root = PromotedRow(
        path='pkg.md',
        state=PromotedState.OVERRIDDEN_BY_ROOT,
        promoted_from='pkg',
        overridden_by='other',
    )
    assert render_promoted_row(row_root).label.plain == '↑ pkg.md  ⚠ overridden by other'


# --- provider branches and session groups -----------------------------------


def test_provider_branch_renders_stats_suffix_and_children() -> None:
    branch = ProviderBranch(
        alias='p',
        version='1.2.3',
        rows=(
            FileRow(path='a.md', state=FileState.WRITTEN),
            CopyRow(
                target='configs',
                source='p/configs',
                state=CopyState.ACTIVE,
            ),
        ),
        stats=AppliedStats(written=1, copies=1),
    )
    node = render_provider_branch(branch)
    assert node.label.plain == 'p@1.2.3  1 written · 1 copies'
    assert [child.label.plain for child in node.children] == [
        '✓ a.md',
        '📋 configs  ← p/configs',
    ]


def test_provider_branch_pending_stats_render_bracketed_counts() -> None:
    branch = ProviderBranch(
        alias='p',
        stats=PendingStats(applied=1, not_applied=2, copies=3),
    )
    node = render_provider_branch(branch)
    assert node.label.plain == 'p  [1 applied, 2 not applied, 3 copies]'


def test_provider_branch_all_applied_pending_stats_render_file_count() -> None:
    one = render_provider_branch(
        ProviderBranch(alias='p', stats=PendingStats(applied=1, not_applied=0)),
    )
    assert one.label.plain == 'p  [1 file]'
    two = render_provider_branch(
        ProviderBranch(alias='p', stats=PendingStats(applied=2, not_applied=0)),
    )
    assert two.label.plain == 'p  [2 files]'


def test_provider_branch_link_hyperlinks_alias(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch('repolish.reporting.leaves.supports_hyperlinks', new=True)
    ctx = tmp_path / 'provider-context.json'
    node = render_provider_branch(ProviderBranch(alias='p', link=ctx))
    assert node.label.plain.startswith('p')
    assert any(f'link file://{ctx}' in str(span.style) for span in node.label.spans)


def test_session_group_renders_title_branches_and_promoted() -> None:
    group = SessionGroup(
        title='Standalone',
        branches=(ProviderBranch(alias='p'),),
        promoted=(PromotedRow(path='pkg.md', state=PromotedState.WRITTEN),),
    )
    node = render_session_group(group)
    assert node.label.plain == 'Standalone'
    assert node.children[0].label.plain == 'p'
    promoted_group = node.children[1]
    assert promoted_group.label.plain == 'Promoted'
    assert promoted_group.children[0].label.plain == '↑ pkg.md  promoted from '


def test_render_session_groups_preserves_group_order() -> None:
    groups = [
        SessionGroup(title='Root'),
        SessionGroup(title='Member: pkg'),
        SessionGroup(title='Standalone'),
    ]
    nodes = render_session_groups(groups)
    assert [node.label.plain for node in nodes] == [
        'Root',
        'Member: pkg',
        'Standalone',
    ]


# --- post-process groups -----------------------------------------------------


def test_command_row_ok_renders_duration() -> None:
    node = render_command_row(
        CommandRow(raw='make fmt', state=CommandState.OK, duration_ms=1500),
    )
    assert node.label.plain.startswith('✓ make fmt  ok (')
    assert 'green' in _styles(node)


def test_command_row_failed_renders_error_or_exit_code() -> None:
    error = render_command_row(
        CommandRow(raw='make fmt', state=CommandState.FAILED, error='boom'),
    )
    assert error.label.plain == '✗ make fmt  FAILED boom'
    exited = render_command_row(
        CommandRow(raw='make fmt', state=CommandState.FAILED, returncode=2),
    )
    assert exited.label.plain == '✗ make fmt  FAILED exit 2'


def test_command_row_not_run_renders_reason() -> None:
    node = render_command_row(
        CommandRow(raw='make fmt', state=CommandState.NOT_RUN),
    )
    assert node.label.plain == '✗ make fmt  not run (previous command failed)'


def test_post_process_group_renders_counts_link_and_subgroups(
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch('repolish.reporting.nodes.supports_hyperlinks', new=True)
    report = tmp_path / 'report.txt'
    group = PostProcessGroup(
        label='pkg',
        link=report,
        commands=(CommandRow(raw='make fmt', state=CommandState.OK),),
        subgroups=(
            PostProcessGroup(
                label='promoted files',
                commands=(
                    CommandRow(
                        raw='make lint',
                        state=CommandState.FAILED,
                        error='bad',
                    ),
                ),
                failed=1,
            ),
        ),
        ok=1,
        failed=1,
    )
    node = render_post_process_group(group)
    assert node.label.plain == 'pkg  1 ok · 1 failed [details]'
    assert node.children[0].label.plain == '✓ make fmt  ok (0ms)'
    assert node.children[1].label.plain == 'promoted files  1 failed'
    assert node.children[1].children[0].label.plain == '✗ make lint  FAILED bad'


def test_insertion_catalog_renders_note_provider_and_rows() -> None:
    nodes = render_insertion_catalog(
        [
            InsertionCatalogGroup(
                provider='alpha',
                functions=(
                    InsertionFunctionRow(
                        name='render-year',
                        summary='Show the current year.',
                        files=('a.md', 'b.md'),
                    ),
                ),
            ),
        ],
    )
    assert nodes[0].label.plain == ('files gate developer markers; template zones may call any listed function')
    assert nodes[1].label.plain == 'alpha (1 functions)'
    fn = nodes[1].children[0]
    assert fn.label.plain == 'render-year  - Show the current year.'
    assert fn.children[0].label.plain == 'files (repolish:on markers): a.md, b.md'


def test_insertion_catalog_styles_match_the_tree_conventions() -> None:
    nodes = render_insertion_catalog(
        [
            InsertionCatalogGroup(
                provider='alpha',
                functions=(InsertionFunctionRow(name='render-year', summary='Year.'),),
            ),
        ],
    )
    assert nodes[0].label.style == 'dim'
    assert nodes[1].label.style == 'bold'
    assert 'dim' in _styles(nodes[1])


def test_insertion_catalog_empty_groups_render_only_the_note() -> None:
    assert len(render_insertion_catalog([])) == 1


# --- lint report -------------------------------------------------------------


def test_lint_templates_ok_and_failed_render_markers() -> None:
    nodes = render_lint_templates(
        [
            LintTemplateRow(path='a.md', state=LintState.OK),
            LintTemplateRow(
                path='b.md',
                state=LintState.FAILED,
                render_error='boom',
            ),
        ],
    )
    assert [node.label.plain for node in nodes] == ['✓ a.md', '✗ b.md']
    assert 'green' in _styles(nodes[0])
    assert 'red' in _styles(nodes[1])
    assert nodes[0].children == []
    assert nodes[1].children[0].label.plain == 'render: boom'


def test_lint_template_renders_findings_as_children() -> None:
    node = render_lint_templates(
        [
            LintTemplateRow(
                path='a.md',
                state=LintState.FAILED,
                issues=(LintIssueRow(chain='x.y', reason="'x' not in context"),),
                warnings=("insert zone 'b': brand it",),
                render_error='boom',
            ),
        ],
    )[0]
    warning, issue, render_error = node.children
    assert warning.label.plain == "⚠ insert zone 'b': brand it"
    assert 'yellow' in _styles(warning)
    assert issue.label.plain == "• x.y: 'x' not in context"
    assert issue.label.spans[0].style == 'bold'
    assert render_error.label.plain == 'render: boom'


def test_lint_templates_empty_rows_render_nothing() -> None:
    assert render_lint_templates([]) == []


def test_unmapped_sources_render_yellow_paths() -> None:
    nodes = render_unmapped_sources(
        [UnmappedSourceRow(path='_repolish.orphan.toml')],
    )
    assert [node.label.plain for node in nodes] == ['_repolish.orphan.toml']
    assert nodes[0].label.style == 'yellow'
    assert render_unmapped_sources([]) == []
