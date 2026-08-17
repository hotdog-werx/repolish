"""Tests for writing replacement text into insertion blocks."""

from dataclasses import dataclass
from textwrap import dedent

import pytest

from repolish.insertions import (
    InsertionBlock,
    Renderer,
    WriteBackResult,
    write_back,
)


@dataclass
class TCase:
    name: str
    text: str
    expected: str
    render: Renderer
    comment_styles: tuple[str, ...] | None = None


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='html_style_replacement',
            text="""
                before
                <!-- repolish:on:docs render foo true -->
                alpha
                beta
                <!-- repolish:off:docs -->
                after
                """,
            expected="""
                before
                <!-- repolish:on:docs render foo true -->
                rendered-docs
                <!-- repolish:off:docs -->
                after
                """,
            render=lambda block: 'rendered-docs' if block.tag == 'docs' else '',
        ),
        TCase(
            name='html_style_replacement_indented',
            text="""
                before
                    <!-- repolish:on:docs render foo true -->
                    alpha
                    beta
                    <!-- repolish:off:docs -->
                after
                """,
            expected="""
                before
                    <!-- repolish:on:docs render foo true -->
                rendered-docs
                    <!-- repolish:off:docs -->
                after
                """,
            render=lambda block: 'rendered-docs\n' if block.tag == 'docs' else '',
        ),
        TCase(
            name='hash_style_replacement',
            text="""
                # repolish:on:docs render foo true
                alpha
                beta
                # repolish:off:docs
                """,
            expected="""# repolish:on:docs render foo true\nrendered-docs\n# repolish:off:docs""",
            render=lambda block: 'rendered-docs' if block.tag == 'docs' else '',
            comment_styles=('hash',),
        ),
        TCase(
            name='repeated_tags_are_independent',
            text="""
                intro
                <!-- repolish:on:dup render -->
                first
                <!-- repolish:off:dup -->
                middle
                <!-- repolish:on:dup render -->
                second
                <!-- repolish:off:dup -->
                outro
                """,
            expected="""
                intro
                <!-- repolish:on:dup render -->
                first:dup
                <!-- repolish:off:dup -->
                middle
                <!-- repolish:on:dup render -->
                second:dup
                <!-- repolish:off:dup -->
                outro
                """,
            render=lambda block: f'{block.body.strip()}:dup',
        ),
        TCase(
            name='handle_mixed_styles',
            text="""
                intro
                /* repolish:on:dup render */
                first
                /* repolish:off:dup */
                middle
                // repolish:on:dup render
                second
                // repolish:off:dup
                outro
                """,
            expected="""
                intro
                /* repolish:on:dup render */
                first:dup
                /* repolish:off:dup */
                middle
                // repolish:on:dup render
                second:dup
                // repolish:off:dup
                outro
                """,
            render=lambda block: f'{block.body.strip()}:dup',
        ),
        TCase(
            name='block_style_replacement',
            text="""
                /* repolish:on:style render src styles.css */
                body { color: red; }
                /* repolish:off:style */
                """,
            expected="""
                /* repolish:on:style render src styles.css */
                body { color: blue; }
                /* repolish:off:style */
                """,
            render=lambda block: 'body { color: blue; }' if block.tag == 'style' else '',
            comment_styles=('block',),
        ),
        TCase(
            name='renderer_exception_returns_empty_string',
            text="""
                <!-- repolish:on:docs render -->
                alpha
                <!-- repolish:off:docs -->
                """,
            expected="""
                <!-- repolish:on:docs render -->
                <!-- repolish:off:docs -->
                """,
            render=lambda _: (_ for _ in ()).throw(RuntimeError('boom')),
        ),
        TCase(
            name='no_blocks_returns_original_text',
            text='plain text\nwith no markers\n',
            expected='plain text\nwith no markers\n',
            render=lambda block: block.body,
        ),
    ],
    ids=lambda c: c.name,
)
def test_write_back(case: TCase) -> None:
    text = dedent(case.text).lstrip('\n').rstrip('\n')
    expected = dedent(case.expected).lstrip('\n').rstrip('\n')
    result = write_back(
        text,
        case.render,
        comment_styles=case.comment_styles,
    )
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_uses_block_metadata() -> None:
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs render foo true -->
        alpha
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    def render(block: InsertionBlock) -> str:
        assert block.tag == 'docs'
        assert block.function == 'render'
        assert block.args == ('foo', 'true')
        return 'rendered-docs'

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs render foo true -->
        rendered-docs
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )
    result = write_back(text, render)
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_resolves_registry_functions() -> None:
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs render foo true -->
        alpha
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    registry = {
        'render': lambda *args: f'{args[0]}={args[1]}',
    }

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs render foo true -->
        foo=true
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, registry)
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_resolves_qualified_name_to_unqualified_registry() -> None:
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs alpha:render foo true -->
        alpha
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    registry = {
        'render': lambda *args: f'{args[0]}={args[1]}',
    }

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs alpha:render foo true -->
        foo=true
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, registry)
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_registry_calls_noarg_renderer() -> None:
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs render -->
        alpha
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    registry = {
        'render': lambda: 'from-noarg-renderer',
    }

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs render -->
        from-noarg-renderer
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, registry)
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_records_missing_renderer_as_diagnostic() -> None:
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs missing-renderer -->
        alpha
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, {'render': lambda: 'unused'})

    assert isinstance(result, WriteBackResult)
    assert result.total_blocks == 1
    assert result.failed_blocks == 1
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].tag == 'docs'
    assert "No renderer registered for function 'missing-renderer'." in result.diagnostics[0].message


def test_write_back_registry_preserves_quoted_args_with_spaces() -> None:
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs some-function 'this is the first arg' 'second arg' 3 -->
        alpha
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    registry = {
        'some-function': lambda *args: '|'.join(args),
    }

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs some-function 'this is the first arg' 'second arg' 3 -->
        this is the first arg|second arg|3
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, registry)
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected
