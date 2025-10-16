from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from repolish.processors import (
    apply_regex_replacements,
    extract_patterns,
    replace_tags_in_content,
    replace_text,
    safe_file_read,
)


@dataclass
class ReplaceTextTestCase:
    id: str
    template: str
    local_content: str
    expected: str
    """Test extracting tag blocks and regex patterns from content."""
    content = dedent("""
        Some text here.
        ## repolish-start[header]
        This is a header block.
        ## repolish-end[header]
        More text.
        ## repolish-regex[version]: __version__ = "(.+?)"
        ## repolish-regex[author]: __author__ = "(.+?)"
        End of content.
    """).strip()

    patterns = extract_patterns(content)

    expected_tag_blocks = {'header': '\nThis is a header block.\n'}
    expected_regexes = {
        'version': '__version__ = "(.+?)"',
        'author': '__author__ = "(.+?)"',
    }

    assert patterns.tag_blocks == expected_tag_blocks
    assert patterns.regexes == expected_regexes


def test_safe_file_read_existing_file(tmp_path: Path):
    """Test safe_file_read with an existing file."""
    test_file = tmp_path / 'test.txt'
    test_content = 'Hello, world!'
    test_file.write_text(test_content)

    result = safe_file_read(test_file)
    assert result == test_content


def test_safe_file_read_nonexistent_file(tmp_path: Path):
    """Test safe_file_read with a nonexistent file."""
    nonexistent_file = tmp_path / 'nonexistent.txt'

    result = safe_file_read(nonexistent_file)
    assert result == ''


def test_safe_file_read_directory(tmp_path: Path):
    """Test safe_file_read with a directory (should return empty string)."""
    result = safe_file_read(tmp_path)
    assert result == ''


def test_replace_tags_in_content():
    """Test replacing tag blocks in content."""
    content = dedent("""
        Start of file.
          ## repolish-start[header]
          Old header content.
          ## repolish-end[header]
        Middle content.
          ## repolish-start[footer]
          Old footer.
          ## repolish-end[footer]
        End of file.
    """).strip()

    tags = {'header': 'New Header Content', 'footer': 'New Footer Content'}

    result = replace_tags_in_content(content, tags)

    expected = 'Start of file.New Header ContentMiddle content.New Footer ContentEnd of file.'

    assert result == expected


def test_replace_tags_in_content_empty_replacement():
    """Test replacing tag blocks with empty strings."""
    content = dedent("""
        Start.
          ## repolish-start[empty]
          This should be removed.
          ## repolish-end[empty]
        End.
    """).strip()

    tags = {'empty': ''}

    result = replace_tags_in_content(content, tags)

    expected = dedent("""
        Start.
          ## repolish-start[empty]
          This should be removed.
          ## repolish-end[empty]
        End.
    """).strip()

    assert result == expected


def test_apply_regex_replacements():
    """Test applying regex replacements."""
    content = dedent("""
        ## repolish-regex[version]: __version__ = "(.+?)"
        ## repolish-regex[author]: __author__ = "(.+?)"
        Some code here.
        print("Version: {{version}}")
        print("Author: {{author}}")
    """).strip()

    regexes = {
        'version': '__version__ = "(.+?)"',
        'author': '__author__ = "(.+?)"',
    }

    local_content = dedent("""
        __version__ = "1.0.0"
        __author__ = "Test Author"
        Some other code.
    """).strip()

    result = apply_regex_replacements(content, regexes, local_content)

    expected = dedent("""
        Some code here.
        print("Version: {{version}}")
        print("Author: {{author}}")
    """).strip()

    assert result == expected


@pytest.mark.parametrize(
    'test_case',
    [
        ReplaceTextTestCase(
            id='basic_tag_and_regex_replacement',
            template=dedent("""
                # My Project
                  ## repolish-start[description]
                  Default description.
                  ## repolish-end[description]

                Version: ## repolish-regex[version]: __version__ = "(.+?)"
                Author: ## repolish-regex[author]: __author__ = "(.+?)"
            """).strip(),
            local_content=dedent("""
                __version__ = "2.0.0"
                __author__ = "Jane Doe"
                description = "A test project"
            """).strip(),
            expected='# My Project\n  Default description.\n  \n',
        ),
        ReplaceTextTestCase(
            id='only_tags',
            template=dedent("""
                Header:
                  ## repolish-start[header]
                  Old header
                  ## repolish-end[header]
                Footer:
                  ## repolish-start[footer]
                  Old footer
                  ## repolish-end[footer]
            """).strip(),
            local_content='',
            expected='Header:\n  Old header\n  Footer:\n  ## repolish-start[footer]\n  Old footer\n  ## repolish-end[footer]',
        ),
        ReplaceTextTestCase(
            id='only_regexes',
            template=dedent("""
                Code version: ## repolish-regex[ver]: version = "(.+?)"
                Code author: ## repolish-regex[auth]: author = "(.+?)"
            """).strip(),
            local_content=dedent("""
                version = "1.5.0"
                author = "John Smith"
            """).strip(),
            expected='',
        ),
    ],
    ids=lambda x: x.id,
)
def test_replace_text(test_case: ReplaceTextTestCase):
    """Test the main replace_text function with various cases."""
    result = replace_text(test_case.template, test_case.local_content)
    assert result == test_case.expected


def test_replace_text_with_anchor_dictionary():
    """Ensure anchors_dictionary replaces tag blocks in the template."""
    template = dedent("""
        FROM ubuntu:20.04
        RUN apt-get update
          ## repolish-start[custom-install]
          ## repolish-end[custom-install]

        USER ${CTR_USER_UID}
    """).strip()

    anchors = {
        'custom-install': 'RUN apt-get update\nRUN apt-get install -y vim',
    }

    result = replace_text(template, '', anchors_dictionary=anchors)

    # Anchors should be injected and the repolish markers removed
    assert '## repolish-start' not in result
    assert 'RUN apt-get install -y vim' in result


def test_replace_text_with_no_anchor_uses_default():
    """When no anchor is provided the template's default block content remains."""
    template = dedent("""
        Header:
          ## repolish-start[header]
          Default header content.
          ## repolish-end[header]
        Footer.
    """).strip()

    result = replace_text(template, '', anchors_dictionary={})

    # Default content in the template should still be present
    assert 'Default header content.' in result
