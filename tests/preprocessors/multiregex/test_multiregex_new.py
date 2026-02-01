"""Tests for multiregex preprocessor functionality."""

from dataclasses import dataclass
from textwrap import dedent

import pytest

from repolish.processors import (
    _extract_block_content,
    _extract_values_from_block,
    _is_key_value_line,
    _replace_key_value,
    apply_multiregex_replacements,
)


@dataclass
class MultiregexTestCase:
    id: str
    content: str
    multiregex_blocks: dict[str, str]
    multiregexes: dict[str, str]
    local_content: str
    expected: str


@pytest.mark.parametrize(
    'test_case',
    [
        MultiregexTestCase(
            id='missing_block',
            content='## repolish-multiregex[missing]: .*\n',
            multiregex_blocks={},  # No blocks defined
            multiregexes={'missing': '.*'},
            local_content='some content',
            expected='## repolish-multiregex[missing]: .*\n',  # Should return content unchanged
        ),
        MultiregexTestCase(
            id='block_not_found_in_local_file',
            content=dedent("""\
                ## repolish-multiregex-block[test]: ^\\[nonexistent\\]
                ## repolish-multiregex[test]: .*
                key = "default"
                """),
            multiregex_blocks={'test': r'^\[nonexistent\]'},
            multiregexes={'test': '.*'},
            local_content='[existing]\nkey = value',
            expected=dedent("""\
                ## repolish-multiregex-block[test]: ^\\[nonexistent\\]
                ## repolish-multiregex[test]: .*
                key = "default"
                """),  # Should return content unchanged
        ),
        MultiregexTestCase(
            id='successful_replacement',
            content=dedent("""\
                [tools]
                ## repolish-multiregex-block[tools]: ^\\[tools\\](.*?)(?=\\n\\[|\\Z)
                ## repolish-multiregex[tools]: ^(")?([^"=\\s]+)(")?\\s*=\\s*"([^"]+)"$
                uv = "0.0.0"
                dprint = "0.0.0"
                """),
            multiregex_blocks={'tools': r'^\[tools\](.*?)(?=\n\[|\Z)'},
            multiregexes={'tools': r'^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$'},
            local_content=dedent("""\
                [tools]
                uv = "0.7.20"
                dprint = "0.50.1"
                starship = "1.0.0"
                """),
            expected=dedent("""\
                [tools]
                uv = "0.7.20"
                dprint = "0.50.1"
                """),
        ),
        MultiregexTestCase(
            id='multiple_sections',
            content=dedent("""\
                [tools]
                ## repolish-multiregex-block[tools]: ^\\[tools\\](.*?)(?=\\n\\[|\\Z)
                ## repolish-multiregex[tools]: ^(")?([^"=\\s]+)(")?\\s*=\\s*"([^"]+)"$
                uv = "0.0.0"

                [settings]
                ## repolish-multiregex-block[settings]: ^\\[settings\\](.*?)(?=\\n\\[|\\Z)
                ## repolish-multiregex[settings]: ^(")?([^"=\\s]+)(")?\\s*=\\s*"([^"]+)"$
                debug = "false"
                """),
            multiregex_blocks={
                'tools': r'^\[tools\](.*?)(?=\n\[|\Z)',
                'settings': r'^\[settings\](.*?)(?=\n\[|\Z)',
            },
            multiregexes={
                'tools': r'^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$',
                'settings': r'^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$',
            },
            local_content=dedent("""\
                [tools]
                uv = "0.7.20"

                [settings]
                debug = "true"
                """),
            expected=dedent("""\
                [tools]
                uv = "0.7.20"

                [settings]
                debug = "true"
                """),
        ),
    ],
    ids=lambda x: x.id,
)
def test_apply_multiregex_replacements(test_case: MultiregexTestCase):
    """Test the main multiregex replacement function."""
    result = apply_multiregex_replacements(
        test_case.content,
        test_case.multiregex_blocks,
        test_case.multiregexes,
        test_case.local_content,
    )
    assert result == test_case.expected


def test_extract_block_content_found():
    """Test successful block extraction."""
    block_regex = r'^\[tools\](.*?)(?=\n\[|\Z)'
    local_content = dedent("""\
        [settings]
        key = value

        [tools]
        uv = "0.7.20"
        dprint = "0.50.1"

        [other]
        """)
    result = _extract_block_content(block_regex, local_content, 'tools')
    expected = '\nuv = "0.7.20"\ndprint = "0.50.1"\n'
    assert result == expected


def test_extract_block_content_not_found():
    """Test when block regex doesn't match."""
    block_regex = r'^\[nonexistent\]'
    local_content = '[existing]\nkey = value'
    result = _extract_block_content(block_regex, local_content, 'test')
    assert result is None


def test_extract_values_four_capture_groups():
    """Test extraction with 4 capture groups (quoted keys and values)."""
    multi_regex = r'^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$'
    block_content = 'uv = "0.7.20"\ndprint = "0.50.1"'
    result = _extract_values_from_block(multi_regex, block_content, 'tools')
    expected = {'uv': '0.7.20', 'dprint': '0.50.1'}
    assert result == expected


def test_extract_values_two_capture_groups():
    """Test extraction with 2 capture groups (simpler format)."""
    multi_regex = r'^([^=]+)=(.*)$'
    block_content = 'uv=0.7.20\ndprint=0.50.1'
    result = _extract_values_from_block(multi_regex, block_content, 'tools')
    expected = {'uv': '0.7.20', 'dprint': '0.50.1'}
    assert result == expected


def test_extract_values_no_matches():
    """Test when regex doesn't match anything."""
    multi_regex = r'^\d+'
    block_content = 'uv = 0.7.20'
    result = _extract_values_from_block(multi_regex, block_content, 'tools')
    assert result == {}


def test_is_key_value_line_valid():
    """Test various valid key=value line formats."""
    assert _is_key_value_line('key = "value"')
    assert _is_key_value_line('"key" = "value"')
    assert _is_key_value_line('key="value"')
    assert _is_key_value_line('  key  =  "value"  ')


def test_is_key_value_line_invalid():
    """Test lines that are not key=value format."""
    assert not _is_key_value_line('[section]')
    assert not _is_key_value_line('# comment')
    assert not _is_key_value_line('key = value')  # no quotes


def test_replace_key_value_successful():
    """Test successful key-value replacement."""
    line = 'uv = "0.0.0"'
    values = {'uv': '0.7.20', 'dprint': '0.50.1'}
    result = _replace_key_value(line, values)
    assert result == 'uv = "0.7.20"'


def test_replace_key_value_quoted_key():
    """Test replacement with quoted keys."""
    line = '"uv" = "0.0.0"'
    values = {'uv': '0.7.20'}
    result = _replace_key_value(line, values)
    assert result == '"uv" = "0.7.20"'


def test_replace_key_value_key_not_in_values():
    """Test when key is not in values dict (should keep default)."""
    line = 'missing = "default"'
    values = {'other': 'value'}
    result = _replace_key_value(line, values)
    assert result == 'missing = "default"'


def test_replace_key_value_no_match():
    """Test when line doesn't match key=value pattern."""
    line = '[section]'
    values = {'key': 'value'}
    result = _replace_key_value(line, values)
    assert result == '[section]'
