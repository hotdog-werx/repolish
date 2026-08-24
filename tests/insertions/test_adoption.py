"""Unit tests for adopt_local_insertion_markers."""

from __future__ import annotations

from repolish.insertions.adoption import adopt_local_insertion_markers


def test_no_markers_returns_content_unchanged() -> None:
    rendered = 'plain content\n'
    local = 'other content\n'
    assert adopt_local_insertion_markers(rendered, local) == rendered


def test_missing_local_file_keeps_template_defaults() -> None:
    rendered = '<!-- repolish:on:status render-status ready -->\n<!-- repolish:off:status -->\n'
    assert adopt_local_insertion_markers(rendered, '') == rendered


def test_adopts_args_from_local_marker() -> None:
    rendered = '# header\n\n<!-- repolish:on:status render-status ready -->\n<!-- repolish:off:status -->\n'
    local = '# header\n\n<!-- repolish:on:status render-status beta -->\nSTATUS=ready\n<!-- repolish:off:status -->\n'
    result = adopt_local_insertion_markers(rendered, local)
    assert '<!-- repolish:on:status render-status beta -->' in result
    assert '<!-- repolish:off:status -->' in result


def test_adopts_function_swap_from_local_marker() -> None:
    rendered = '<!-- repolish:on:status render-status ready -->\n<!-- repolish:off:status -->\n'
    local = '<!-- repolish:on:status render-mode dark -->\nMODE=dark\n<!-- repolish:off:status -->\n'
    result = adopt_local_insertion_markers(rendered, local)
    assert result.startswith('<!-- repolish:on:status render-mode dark -->')

    # The closing marker stays template-owned.
    assert '<!-- repolish:off:status -->' in result


def test_local_body_is_never_adopted() -> None:
    rendered = '<!-- repolish:on:status render-status ready -->\n\n<!-- repolish:off:status -->\n'
    local = '<!-- repolish:on:status render-status beta -->\nuser scribbles here\n<!-- repolish:off:status -->\n'
    result = adopt_local_insertion_markers(rendered, local)
    assert 'user scribbles here' not in result
    assert '\n\n<!-- repolish:off:status -->' in result


def test_same_tag_blocks_pair_by_occurrence_order() -> None:
    rendered = (
        '<!-- repolish:on:n render-x one -->\n<!-- repolish:off:n -->\n'
        'middle\n'
        '<!-- repolish:on:n render-x two -->\n<!-- repolish:off:n -->\n'
    )
    local = (
        '<!-- repolish:on:n render-x ONE -->\n<!-- repolish:off:n -->\n'
        'middle\n'
        '<!-- repolish:on:n render-x TWO -->\n<!-- repolish:off:n -->\n'
    )
    result = adopt_local_insertion_markers(rendered, local)
    assert 'render-x ONE' in result
    assert 'render-x TWO' in result


def test_local_missing_second_block_keeps_template_default() -> None:
    rendered = (
        '<!-- repolish:on:n render-x one -->\n<!-- repolish:off:n -->\n'
        '<!-- repolish:on:n render-x two -->\n<!-- repolish:off:n -->\n'
    )
    local = '<!-- repolish:on:n render-x ONE -->\n<!-- repolish:off:n -->\n'
    result = adopt_local_insertion_markers(rendered, local)
    assert 'render-x ONE' in result
    assert 'render-x two' in result


def test_extra_local_blocks_are_ignored() -> None:
    rendered = '<!-- repolish:on:n render-x one -->\n<!-- repolish:off:n -->\n'
    local = (
        '<!-- repolish:on:n render-x ONE -->\n<!-- repolish:off:n -->\n'
        '<!-- repolish:on:n render-x EXTRA -->\n<!-- repolish:off:n -->\n'
    )
    result = adopt_local_insertion_markers(rendered, local)
    assert 'render-x ONE' in result
    assert 'EXTRA' not in result


def test_block_only_in_local_is_not_adopted() -> None:
    rendered = '<!-- repolish:on:a render-a -->\n<!-- repolish:off:a -->\n'
    local = '<!-- repolish:on:b render-b -->\n<!-- repolish:off:b -->\n'
    assert adopt_local_insertion_markers(rendered, local) == rendered


def test_hash_comment_style_markers_adopted() -> None:
    rendered = '# repolish:on:cfg render-config foo\n# repolish:off:cfg\n'
    local = '# repolish:on:cfg render-config bar=1\n# repolish:off:cfg\n'
    result = adopt_local_insertion_markers(rendered, local)
    assert 'render-config bar=1' in result


def test_user_can_switch_comment_style_of_marker() -> None:
    rendered = '<!-- repolish:on:cfg render-config foo -->\n<!-- repolish:off:cfg -->\n'
    local = '# repolish:on:cfg render-config foo\nbody\n# repolish:off:cfg\n'
    result = adopt_local_insertion_markers(rendered, local)
    assert result.startswith('# repolish:on:cfg render-config foo')


def test_identical_markers_return_unchanged() -> None:
    rendered = '<!-- repolish:on:status render-status ready -->\n<!-- repolish:off:status -->\n'
    assert adopt_local_insertion_markers(rendered, rendered) == rendered


def test_adoption_is_idempotent() -> None:
    rendered = '<!-- repolish:on:status render-status ready -->\n<!-- repolish:off:status -->\n'
    local = '<!-- repolish:on:status render-status beta -->\nSTATUS=beta\n<!-- repolish:off:status -->\n'
    once = adopt_local_insertion_markers(rendered, local)
    assert adopt_local_insertion_markers(once, local) == once


def test_malformed_local_markers_keep_template_defaults() -> None:
    rendered = '<!-- repolish:on:status render-status ready -->\n<!-- repolish:off:status -->\n'
    local = '<!-- repolish:on:status render-status beta -->\nSTATUS=ready\n'  # never closed
    assert adopt_local_insertion_markers(rendered, local) == rendered
