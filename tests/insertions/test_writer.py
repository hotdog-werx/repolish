"""Tests for writing replacement text into insertion blocks."""

from dataclasses import dataclass
from textwrap import dedent

import pytest

from repolish.insertions import InsertionBlock, Renderer, WriteBackResult, write_back


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
            expected="""<!-- repolish:on:docs render -->\n\n<!-- repolish:off:docs -->""",
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
