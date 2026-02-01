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


@dataclass
class KeyValueTestCase:
    id: str
    line: str
    values: dict[str, str]
    expected: str


@pytest.mark.parametrize(
    'test_case',
    [
        KeyValueTestCase(
            id='successful_replacement',
            line='uv = "0.0.0"',
            values={'uv': '0.7.20', 'dprint': '0.50.1'},
            expected='uv = "0.7.20"',
        ),
        KeyValueTestCase(
            id='quoted_key_replacement',
            line='"uv" = "0.0.0"',
            values={'uv': '0.7.20'},
            expected='"uv" = "0.7.20"',
        ),
        KeyValueTestCase(
            id='key_not_in_values',
            line='missing = "default"',
            values={'other': 'value'},
            expected='missing = "default"',
        ),
        KeyValueTestCase(
            id='no_match',
            line='[section]',
            values={'key': 'value'},
            expected='[section]',
        ),
    ],
    ids=lambda x: x.id,
)
def test_replace_key_value(test_case: KeyValueTestCase):
    """Test key-value replacement in various scenarios."""
    result = _replace_key_value(test_case.line, test_case.values)
    assert result == test_case.expected


@dataclass
class BlockContentTestCase:
    id: str
    block_regex: str
    local_content: str
    tag: str
    expected: str | None


@pytest.mark.parametrize(
    'test_case',
    [
        BlockContentTestCase(
            id='block_found',
            block_regex=r'^\[tools\](.*?)(?=\n\[|\Z)',
            local_content=dedent("""\
                [settings]
                key = value

                [tools]
                uv = "0.7.20"
                dprint = "0.50.1"

                [other]
                """),
            tag='tools',
            expected='\nuv = "0.7.20"\ndprint = "0.50.1"\n',
        ),
        BlockContentTestCase(
            id='block_not_found',
            block_regex=r'^\[nonexistent\]',
            local_content='[existing]\nkey = value',
            tag='test',
            expected=None,
        ),
    ],
    ids=lambda x: x.id,
)
def test_extract_block_content(test_case: BlockContentTestCase):
    """Test block content extraction in various scenarios."""
    result = _extract_block_content(
        test_case.block_regex,
        test_case.local_content,
        test_case.tag,
    )
    assert result == test_case.expected


@dataclass
class ExtractValuesTestCase:
    id: str
    multi_regex: str
    block_content: str
    tag: str
    expected: dict[str, str]


@pytest.mark.parametrize(
    'test_case',
    [
        ExtractValuesTestCase(
            id='four_capture_groups',
            multi_regex=r'^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$',
            block_content='uv = "0.7.20"\ndprint = "0.50.1"',
            tag='tools',
            expected={'uv': '0.7.20', 'dprint': '0.50.1'},
        ),
        ExtractValuesTestCase(
            id='two_capture_groups',
            multi_regex=r'^([^=]+)=(.*)$',
            block_content='uv=0.7.20\ndprint=0.50.1',
            tag='tools',
            expected={'uv': '0.7.20', 'dprint': '0.50.1'},
        ),
        ExtractValuesTestCase(
            id='no_matches',
            multi_regex=r'^\d+',
            block_content='uv = 0.7.20',
            tag='tools',
            expected={},
        ),
    ],
    ids=lambda x: x.id,
)
def test_extract_values_from_block(test_case: ExtractValuesTestCase):
    """Test value extraction from block content in various scenarios."""
    result = _extract_values_from_block(
        test_case.multi_regex,
        test_case.block_content,
        test_case.tag,
    )
    assert result == test_case.expected


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
