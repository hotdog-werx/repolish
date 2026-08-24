"""Tests for writing replacement text into insertion blocks."""

from dataclasses import dataclass
from textwrap import dedent
from typing import cast

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
            name='no_tag_names',
            text="""
                intro
                <!-- repolish:on render -->
                first
                <!-- repolish:off -->
                middle
                <!-- repolish:on render -->
                second
                <!-- repolish:off -->
                outro
                """,
            expected="""
                intro
                <!-- repolish:on render -->
                first:dup
                <!-- repolish:off -->
                middle
                <!-- repolish:on render -->
                second:dup
                <!-- repolish:off -->
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


def test_write_back_functionless_marker_renders_empty_body() -> None:
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs -->
        previous-body
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs -->
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, {'render': lambda: 'ignored'})
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected
    assert result.failed_blocks == 0


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


def test_write_back_injects_keyword_only_insertion_block() -> None:
    """Test that keyword-only InsertionBlock params are injected."""
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs kw-block-func -->
        ignored-body
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    def kw_block_func(*, block: InsertionBlock) -> str:
        return f'tag={block.tag}:args={",".join(block.args)}'

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs kw-block-func -->
        tag=docs:args=
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, {'kw-block-func': kw_block_func})
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_with_string_block_annotation() -> None:
    """Test that string 'InsertionBlock' annotation path is covered."""
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs string-annotated-func hello world -->
        ignored-body
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    # Use string annotation to cover that code path
    ns: dict[str, object] = {}
    exec(  # noqa: S102
        'def string_annotated_func(*, block: "InsertionBlock") -> str:\n'
        '    return f"str-annotated:{block.tag}:{":".join(block.args)}"',
        ns,
    )
    string_annotated_func = ns['string_annotated_func']

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs string-annotated-func hello world -->
        str-annotated:docs:hello:world
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(
        text,
        cast(
            'dict[str, Renderer]',
            {'string-annotated-func': string_annotated_func},
        ),
    )
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_two_positional_params() -> None:
    """Test function with two positional params to cover continue path in _build_call_kwargs."""
    text = (
        dedent(
            """
        before
        <!-- repolish:on:docs two-pos-func arg1 arg2 -->
        ignored-body
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    def two_pos_func(arg1: str, arg2: str) -> str:
        return f'{arg1}:{arg2}'

    expected = (
        dedent(
            """
        before
        <!-- repolish:on:docs two-pos-func arg1 arg2 -->
        arg1:arg2
        <!-- repolish:off:docs -->
        after
        """,
        )
        .lstrip('\n')
        .rstrip('\n')
    )

    result = write_back(text, {'two-pos-func': two_pos_func})
    assert isinstance(result, WriteBackResult)
    assert result.text.rstrip('\n') == expected


def test_write_back_populates_file_path_in_blocks() -> None:
    """Test that file_path is populated through write_back."""
    text = dedent("""
        <!-- repolish:on:docs render foo -->
        content
        <!-- repolish:off:docs -->
        """).lstrip('\n')

    file_path = 'src/file.txt'
    captured_block = None

    def renderer(block: InsertionBlock) -> str:
        nonlocal captured_block
        captured_block = block
        return f'file:{block.file_path}'

    result = write_back(text, renderer, file_path=file_path)

    assert captured_block is not None
    assert captured_block.file_path == file_path
    assert 'file:src/file.txt' in result.text


def test_write_back_default_file_path_is_empty() -> None:
    """Test that file_path defaults to empty string in write_back."""
    text = dedent("""
        <!-- repolish:on:tag func -->
        body
        <!-- repolish:off:tag -->
        """).lstrip('\n')

    captured_block = None

    def renderer(block: InsertionBlock) -> str:
        nonlocal captured_block
        captured_block = block
        return 'x'

    write_back(text, renderer)

    assert captured_block is not None
    assert captured_block.file_path == ''
