from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from repolish.preprocessors import (
    replace_text,
    safe_file_read,
)
from repolish.utils import write_text_utf8


@dataclass
class ReplaceTextTestCase:
    id: str
    template: str
    local_content: str = ''
    anchors: dict | None = None
    expected_equal: str | None = None
    expected_contains: list[str] | None = None
    expected_not_contains: list[str] | None = None


def test_safe_file_read_existing_file(tmp_path: Path):
    """Test safe_file_read with an existing file."""
    test_file = tmp_path / 'test.txt'
    test_content = 'Hello, wörld! 🌍'
    write_text_utf8(test_file, test_content)

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


@pytest.mark.parametrize(
    'test_case',
    [
        ReplaceTextTestCase(
            id='basic_tag_and_regex_replacement',
            template=dedent("""\
                # My Project
                ## repolish-start[description]
                Default description.
                ## repolish-end[description]

                ## repolish-regex[version]: __version__ = "(.+?)"
                __version__ = "0.0.0"
                ## repolish-regex[author]: __author__ = "(.+?)"
                __author__ = "John Doe"
            """),
            local_content=dedent("""\
                __version__ = "2.0.0"
                __author__ = "Jane Doe"
                description = "A test project"
            """),
            expected_equal=dedent("""\
                # My Project
                Default description.

                __version__ = "2.0.0"
                __author__ = "Jane Doe"
            """),
        ),
        ReplaceTextTestCase(
            id='only_tags',
            template=dedent("""\
                Header:
                <!-- repolish-start[header] -->
                  Old header
                <!-- repolish-end[header] -->
                Footer:
                  ## repolish-start[footer]
                  Old footer
                  ## repolish-end[footer]
            """),
            local_content='',
            # When no anchors are provided the template defaults (inner block
            # content) are preserved but the marker lines are removed.
            expected_equal=dedent("""\
                Header:
                  Old header
                Footer:
                  Old footer
            """),
        ),
        ReplaceTextTestCase(
            id='explicit_empty_anchor_deletes_block',
            template=dedent("""\
                Start.
                /* repolish-start[empty] */
                This should be removed.
                /* repolish-end[empty] */
                End.
            """),
            anchors={'empty': ''},
            expected_equal=dedent("""\
                Start.

                End.
            """),
        ),
        ReplaceTextTestCase(
            id='only_regexes_in_single_line',
            template=dedent("""\
                Code version: ## repolish-regex[ver]: version = "(.+?)"
                ## repolish-regex[auth]: author = "(.+?)"
                author = "default_author"
            """),
            local_content=dedent("""\
                version = "1.5.0"
                author = "John Smith"
            """),
            expected_equal=dedent("""\
                author = "John Smith"
            """),
        ),
        ReplaceTextTestCase(
            id='dockerfile_anchor',
            template=dedent("""\
                FROM ubuntu:20.04
                RUN apt-get update
                ## repolish-start[custom-install]
                ## repolish-end[custom-install]

                USER ${CTR_USER_UID}
            """),
            anchors={
                'custom-install': 'RUN apt-get update\nRUN apt-get install -y vim',
            },
            expected_contains=['RUN apt-get install -y vim'],
            expected_not_contains=['## repolish-start'],
        ),
        ReplaceTextTestCase(
            id='pyproject_keep_version',
            template=dedent("""\
                name: {{cookiecutter.repo_owner}}
                ## repolish-regex[keep-version]: ^version:\\s*(.+)$
                version: 0.0.0
            """),
            local_content=dedent("""\
                version: 1.2.3
                some: other
            """),
            expected_contains=['version: 1.2.3'],
            expected_not_contains=['repolish-regex'],
        ),
        ReplaceTextTestCase(
            id='verbatim_multiline',
            template=dedent("""\
                BEGIN
                    ## repolish-start[block]
                    default
                    ## repolish-end[block]
                END
            """),
            anchors={'block': '\nLINE1\nLINE2\n'},
            expected_contains=['\nLINE1\nLINE2\n'],
            expected_not_contains=['## repolish-start'],
        ),
        ReplaceTextTestCase(
            id='single_line_promoted',
            template=dedent("""\
                Header
                    ## repolish-start[indented]
                        some indented default
                    ## repolish-end[indented]
                Footer
            """),
            anchors={'indented': 'REPLACED'},
            expected_contains=['\nREPLACED\n'],
        ),
        ReplaceTextTestCase(
            id='wrap_multiline',
            template=dedent("""\
                Top
                    ## repolish-start[block]
                    default
                    ## repolish-end[block]
                Bottom
            """),
            anchors={'block': 'LINE1\nLINE2'},
            expected_contains=['\nLINE1\nLINE2\n'],
            expected_not_contains=['## repolish-start'],
        ),
        ReplaceTextTestCase(
            id='start_newline',
            template=dedent("""\
                Top
                    ## repolish-start[b]
                    default
                    ## repolish-end[b]
                Bottom
            """),
            anchors={'b': '\nSTART\nMID'},
            expected_contains=['\nSTART\nMID'],
            expected_not_contains=['## repolish-start'],
        ),
        ReplaceTextTestCase(
            id='end_newline',
            template=dedent("""\
                Top
                    ## repolish-start[c]
                    default
                    ## repolish-end[c]
                Bottom
            """),
            anchors={'c': 'ONE\nTWO\n'},
            expected_contains=['ONE\nTWO\n'],
            expected_not_contains=['## repolish-start'],
        ),
        ReplaceTextTestCase(
            id='inline_between',
            template=dedent("""\
                Hello
                ## repolish-start[tag]
                inner
                ## repolish-end[tag]
                World
            """),
            anchors={'tag': 'X'},
            expected_equal=dedent("""\
                Hello
                X
                World
            """),
        ),
        ReplaceTextTestCase(
            id='inline_adjacent',
            template=dedent("""\
                A
                ## repolish-start[t]
                one
                ## repolish-end[t]
                B
            """),
            anchors={'t': 'Z'},
            expected_equal=dedent("""\
                A
                Z
                B
            """),
        ),
        ReplaceTextTestCase(
            id='pyproject_test',
            template=dedent("""\
                [tool.poetry]
                name = "{{ cookiecutter.package_name }}"
                version = "0.1.0"

                ## repolish-regex[keep-description]: ^description =\\s(.+)$
                description = "A short description"

                ## repolish-start[extra-deps]
                # optional extra deps (preserved when present)
                ## repolish-end[extra-deps]
            """),
            local_content=dedent("""\
                [tool.poetry]
                name = "myproj"
                version = "0.2.0"

                description = "Local project description"
            """),
            anchors={'extra-deps': 'requests = "^5.30"'},
            expected_equal=dedent("""\
                [tool.poetry]
                name = "{{ cookiecutter.package_name }}"
                version = "0.1.0"

                description = "Local project description"

                requests = "^5.30"
            """),
        ),
        ReplaceTextTestCase(
            id='inline_end_same_line',
            template=dedent("""\
                A
                ## repolish-start[tag]
                inner## repolish-end[tag]
                B
            """),
            anchors={'tag': 'Y'},
            expected_equal=dedent("""\
                A
                Y
                B
            """),
        ),
        ReplaceTextTestCase(
            id='no_anchor_default',
            template=dedent("""\
                Header:
                    ## repolish-start[header]
                    Default header content.
                    ## repolish-end[header]
                Footer.
            """),
            anchors={},
            expected_contains=['Default header content.'],
        ),
        ReplaceTextTestCase(
            id='multiregex_tools_section',
            template=dedent("""\
                [settings]
                experimental = true

                [tools]
                ## repolish-multiregex-block[tools]: ^\\[tools\\](.*?)(?=\\n\\[|\\Z)
                ## repolish-multiregex[tools]: ^(")?([^"=\\s]+)(")?\\s*=\\s*"([^"]+)"$
                uv = "0.0.0"
                dprint = "0.0.0"
                starship = "0.0.0"
            """),
            local_content=dedent("""\
                [settings]
                experimental = true

                [tools]
                uv = "0.7.20"
                dprint = "0.50.1"
                starship = "1.0.0"
            """),
            expected_equal=dedent("""\
                [settings]
                experimental = true

                [tools]
                uv = "0.7.20"
                dprint = "0.50.1"
                starship = "1.0.0"
            """),
        ),
    ],
    ids=lambda x: x.id,
)
def test_replace_text(test_case: ReplaceTextTestCase):
    """Test the main replace_text function with various cases."""
    result = replace_text(
        test_case.template,
        test_case.local_content,
        anchors_dictionary=test_case.anchors or {},
    )
    if test_case.expected_equal is not None:
        assert result == test_case.expected_equal
    if test_case.expected_contains:
        for s in test_case.expected_contains:
            assert s in result
    if test_case.expected_not_contains:
        for s in test_case.expected_not_contains:
            assert s not in result
