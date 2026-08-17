"""Tests for insertion marker parsing."""

from dataclasses import dataclass
from textwrap import dedent

import pytest

from repolish.insertions import parse_text


@dataclass
class TCase:
    name: str
    text: str
    expected_tags: tuple[str, ...] = ()
    expected_functions: tuple[str, ...] = ()
    expected_args: tuple[tuple[str, ...], ...] = ()
    expected_bodies: tuple[str, ...] = ()
    expected_diagnostics: tuple[str, ...] = ()
    comment_styles: tuple[str, ...] | None = None


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='single_block',
            text="""
                # before
                <!-- repolish:on:docs compute_docs foo true -->
                alpha
                beta
                <!-- repolish:off:docs -->
                # after
                """,
            expected_tags=('docs',),
            expected_functions=('compute_docs',),
            expected_args=(('foo', 'true'),),
            expected_bodies=('\nalpha\nbeta\n',),
        ),
        TCase(
            name='multiple_blocks',
            text="""
                intro
                <!-- repolish:on:one a -->
                first
                <!-- repolish:off:one -->
                middle
                <!-- repolish:on:two b 3 -->
                second
                <!-- repolish:off:two -->
                outro
                """,
            expected_tags=('one', 'two'),
            expected_functions=('a', 'b'),
            expected_args=((), ('3',)),
            expected_bodies=('\nfirst\n', '\nsecond\n'),
        ),
        TCase(
            name='quoted_args_with_spaces',
            text="""
                <!-- repolish:on:docs some-function 'this is the first arg' "second arg" 3 -->
                content
                <!-- repolish:off:docs -->
                """,
            expected_tags=('docs',),
            expected_functions=('some-function',),
            expected_args=(
                (
                    'this is the first arg',
                    'second arg',
                    '3',
                ),
            ),
            expected_bodies=('\ncontent\n',),
        ),
        TCase(
            name='hash_comment_block',
            text="""
                # repolish:on:docs render foo true
                alpha
                beta
                # repolish:off:docs
                """,
            expected_tags=('docs',),
            expected_functions=('render',),
            expected_args=(('foo', 'true'),),
            expected_bodies=('\nalpha\nbeta\n',),
            comment_styles=('hash',),
        ),
        TCase(
            name='js_comment_block',
            text="""
                // repolish:on:script bundle src main.js
                console.log('hello')
                // repolish:off:script
                """,
            expected_tags=('script',),
            expected_functions=('bundle',),
            expected_args=(('src', 'main.js'),),
            expected_bodies=("\nconsole.log('hello')\n",),
            comment_styles=('js',),
        ),
        TCase(
            name='block_comment_block',
            text="""
                /* repolish:on:style render src styles.css */
                body {
                  color: red;
                }
                /* repolish:off:style */
                """,
            expected_tags=('style',),
            expected_functions=('render',),
            expected_args=(('src', 'styles.css'),),
            expected_bodies=('\nbody {\n  color: red;\n}\n',),
            comment_styles=('block',),
        ),
        TCase(
            name='invalid_style_defaults_to_html',
            text="""
                <!-- repolish:on:docs render foo true -->
                alpha
                <!-- repolish:off:docs -->
                """,
            expected_tags=('docs',),
            expected_functions=('render',),
            expected_args=(('foo', 'true'),),
            expected_bodies=('\nalpha\n',),
            comment_styles=('bogus',),
        ),
        TCase(
            name='no_blocks',
            text='plain text\nwith no markers\n',
        ),
        TCase(
            name='empty_body',
            text='<!-- repolish:on:empty render -->\n<!-- repolish:off:empty -->\n',
            expected_tags=('empty',),
            expected_functions=('render',),
            expected_args=((),),
            expected_bodies=('\n',),
        ),
        TCase(
            name='unclosed_marker',
            text='<!-- repolish:on:broken build -->\ncontent\n',
            expected_diagnostics=('Unclosed insertion marker for tag',),
        ),
        TCase(
            name='missing_open_marker',
            text='<!-- repolish:off:broken -->\n',
            expected_diagnostics=('without a matching opener',),
        ),
        TCase(
            name='missing_function_name',
            text='<!-- repolish:on:bad -->\ncontent\n<!-- repolish:off:bad -->\n',
            expected_diagnostics=('missing a function name',),
        ),
        TCase(
            name='nested_same_tag',
            text="""
                <!-- repolish:on:dup assemble -->
                outer
                <!-- repolish:on:dup nested -->
                inner
                <!-- repolish:off:dup -->
                """,
            expected_tags=('dup',),
            expected_functions=('assemble',),
            expected_args=((),),
            # When a nested same-tag 'on' is skipped, the body includes everything up to the 'off'
            expected_bodies=('\nouter\n<!-- repolish:on:dup nested -->\ninner\n',),
            expected_diagnostics=('already open',),
        ),
        TCase(
            name='invalid_quoted_args',
            text="""
                    <!-- repolish:on:docs some-function 'unterminated -->
                    content
                    <!-- repolish:off:docs -->
                    """,
            expected_diagnostics=('Invalid insertion marker arguments',),
        ),
    ],
    ids=lambda c: c.name,
)
def test_parse_insertions(case: TCase) -> None:
    text = dedent(case.text).lstrip('\n')
    parsed = parse_text(text, comment_styles=case.comment_styles)

    assert [block.tag for block in parsed.blocks] == list(case.expected_tags)
    assert [block.function for block in parsed.blocks] == list(
        case.expected_functions,
    )
    assert [block.args for block in parsed.blocks] == list(case.expected_args)
    assert [block.body for block in parsed.blocks] == list(case.expected_bodies)
    assert parsed.has_insertions is bool(case.expected_tags)

    # Check diagnostics
    if case.expected_diagnostics:
        assert len(parsed.diagnostics) > 0
        for expected in case.expected_diagnostics:
            assert any(expected in d.message for d in parsed.diagnostics), (
                f'Expected diagnostic {expected!r} not found in {parsed.diagnostics}'
            )
