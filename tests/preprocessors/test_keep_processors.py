from dataclasses import dataclass
from textwrap import dedent
from unittest import mock

import pytest

from repolish.preprocessors import extract_patterns, replace_text
from repolish.preprocessors.keep import (
    KeepBlockSpec,
    KeepMarkerSpec,
    apply_keep_replacements,
)


@dataclass
class KeepCase:
    name: str
    template: str
    local_content: str
    expected: str


@pytest.mark.parametrize(
    'case',
    [
        KeepCase(
            name='keep_block_preserves_target_region',
            template=dedent("""\
                Title
                ## repolish-keep-block[readme-custom-block]: start="<!-- start -->" end="<!-- end -->"
                <!-- start -->
                Default text
                <!-- end -->
                Footer
            """),
            local_content=dedent("""\
                Title
                <!-- start -->
                Custom text
                <!-- end -->
                Footer
            """),
            expected=dedent("""\
                Title
                <!-- start -->
                Custom text
                <!-- end -->
                Footer
            """),
        ),
        KeepCase(
            name='keep_rest_preserves_from_marker_to_eof',
            template=dedent("""\
                Header
                ## repolish-keep-rest[repo-overrides]: marker="## repo-overrides"
                ## repo-overrides
                # Placeholder
            """),
            local_content=dedent("""\
                Header
                ## repo-overrides
                allow=1
                deny=2
            """),
            expected=dedent("""\
                Header
                ## repo-overrides
                allow=1
                deny=2
            """),
        ),
        KeepCase(
            name='keep_header_preserves_prefix_and_template_suffix',
            template=dedent("""\
                ## repolish-keep-header[repo-header]: marker="## managed"
                Intro default
                ## managed
                ## repolish-regex[version]: ^version = \"(.+?)\"$
                version = "0.0.0"
            """),
            local_content=dedent("""\
                Developer intro
                ## managed
                version = "1.2.3"
            """),
            expected=dedent("""\
                Developer intro
                ## managed
                version = "1.2.3"
            """),
        ),
        KeepCase(
            name='keep_block_falls_back_to_template_defaults',
            template=dedent("""\
                Title
                ## repolish-keep-block[readme-custom-block]: start="<!-- start -->" end="<!-- end -->"
                <!-- start -->
                Default text
                <!-- end -->
                Footer
            """),
            local_content='Title\nFooter\n',
            expected=dedent("""\
                Title
                <!-- start -->
                Default text
                <!-- end -->
                Footer
            """),
        ),
    ],
    ids=lambda case: case.name,
)
def test_replace_text_keep_directives(case: KeepCase) -> None:
    result = replace_text(case.template, case.local_content)
    assert result == case.expected


def test_extract_patterns_includes_keep_directives() -> None:
    template = dedent("""\
        ## repolish-keep-block[readme-custom-block]: start="<!-- start -->" end="<!-- end -->"
        <!-- start -->
        Default
        <!-- end -->

        ## repolish-keep-rest[repo-overrides]: marker="## repo-overrides"
        ## repo-overrides
        # Placeholder

        ## repolish-keep-header[repo-header]: marker="## managed"
        Intro
        ## managed
    """)

    patterns = extract_patterns(template)

    assert patterns.keep_blocks['readme-custom-block'] == (
        '<!-- start -->',
        '<!-- end -->',
    )
    assert patterns.keep_rest['repo-overrides'] == '## repo-overrides'
    assert patterns.keep_header['repo-header'] == '## managed'


def test_extract_patterns_keep_literals_must_be_strings() -> None:
    template = dedent("""\
        ## repolish-keep-block[readme-custom-block]: start="<!-- start -->" end="<!-- end -->"
        <!-- start -->
        Default
        <!-- end -->
    """)

    with (
        mock.patch(
            'repolish.preprocessors.core.ast.literal_eval',
            return_value=123,
        ),
        pytest.raises(TypeError, match='quoted strings'),
    ):
        extract_patterns(template)


def test_apply_keep_replacements_block_name_not_in_specs() -> None:
    template = dedent("""\
        Top
        ## repolish-keep-block[missing-spec]: start="<<" end=">>"
        <<
        Default
        >>
        Bottom
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={},
        keep_header={},
        local_file_content='',
    )

    assert result == 'Top\n<<\nDefault\n>>\nBottom\n'


def test_apply_keep_replacements_block_template_region_not_found() -> None:
    template = dedent("""\
        Top
        ## repolish-keep-block[block]: start="<<" end=">>"
        Default
        Bottom
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={'block': KeepBlockSpec(start='<<', end='>>')},
        keep_rest={},
        keep_header={},
        local_file_content='',
    )

    assert result == 'Top\nDefault\nBottom\n'


def test_apply_keep_replacements_rest_name_not_in_specs() -> None:
    template = dedent("""\
        Top
        ## repolish-keep-rest[missing-spec]: marker="## marker"
        ## marker
        Default
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={},
        keep_header={},
        local_file_content='',
    )

    assert result == 'Top\n## marker\nDefault\n'


def test_apply_keep_replacements_rest_marker_not_found_in_template() -> None:
    template = dedent("""\
        Top
        ## repolish-keep-rest[repo-overrides]: marker="## marker"
        Default
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={'repo-overrides': KeepMarkerSpec(marker='## marker')},
        keep_header={},
        local_file_content='## marker\ncustom\n',
    )

    assert result == 'Top\nDefault\n'


def test_apply_keep_replacements_rest_uses_template_tail_when_local_missing_marker() -> None:
    template = dedent("""\
        Top
        ## repolish-keep-rest[repo-overrides]: marker="## marker"
        ## marker
        Default
        Tail
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={'repo-overrides': KeepMarkerSpec(marker='## marker')},
        keep_header={},
        local_file_content='Top\nno marker here\n',
    )

    assert result == 'Top\n## marker\nDefault\nTail\n'


def test_apply_keep_replacements_rest_preserves_template_lines_before_marker() -> None:
    template = dedent("""\
        Header
        ## repolish-keep-rest[repo-overrides]: marker="## marker"
        Provider managed line 1
        Provider managed line 2
        ## marker
        Default tail
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={'repo-overrides': KeepMarkerSpec(marker='## marker')},
        keep_header={},
        local_file_content=dedent("""\
            Header
            ## marker
            custom tail
        """),
    )

    assert result == dedent("""\
        Header
        Provider managed line 1
        Provider managed line 2
        ## marker
        custom tail
    """)


def test_apply_keep_replacements_rest_matches_marker_with_crlf_lines() -> None:
    template = 'Header\r\n## repolish-keep-rest[repo-overrides]: marker="## marker"\r\n## marker\r\nDefault tail\r\n'

    local_content = 'Header\r\n## marker\r\ncustom tail\r\n'

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={'repo-overrides': KeepMarkerSpec(marker='## marker')},
        keep_header={},
        local_file_content=local_content,
    )

    assert result == local_content


def test_apply_keep_replacements_header_name_not_in_specs() -> None:
    template = dedent("""\
        ## repolish-keep-header[missing-spec]: marker="## managed"
        Intro
        ## managed
        Managed
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={},
        keep_header={},
        local_file_content='',
    )

    assert result == 'Intro\n## managed\nManaged\n'


def test_apply_keep_replacements_header_marker_not_found_in_template() -> None:
    template = dedent("""\
        ## repolish-keep-header[repo-header]: marker="## managed"
        Intro
        Managed
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={},
        keep_header={'repo-header': KeepMarkerSpec(marker='## managed')},
        local_file_content='Local intro\n## managed\nLocal tail\n',
    )

    assert result == 'Intro\nManaged\n'


def test_apply_keep_replacements_header_uses_template_prefix_when_local_missing_marker() -> None:
    template = dedent("""\
        ## repolish-keep-header[repo-header]: marker="## managed"
        Intro default
        ## managed
        Managed tail
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={},
        keep_header={'repo-header': KeepMarkerSpec(marker='## managed')},
        local_file_content='Local intro without marker\n',
    )

    assert result == 'Intro default\n## managed\nManaged tail\n'


def test_apply_keep_replacements_header_must_be_at_file_start() -> None:
    template = dedent("""\
        Prefix line
        ## repolish-keep-header[repo-header]: marker="## managed"
        Intro default
        ## managed
        Managed tail
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={},
        keep_rest={},
        keep_header={'repo-header': KeepMarkerSpec(marker='## managed')},
        local_file_content=dedent("""\
            Local intro
            ## managed
            Local tail
        """),
    )

    assert result == 'Prefix line\nIntro default\n## managed\nManaged tail\n'


def test_apply_keep_replacements_block_local_has_start_but_no_end_marker() -> None:
    """Test keep-block when local file has start marker but missing end marker."""
    template = dedent("""\
        Top
        ## repolish-keep-block[block]: start="<<" end=">>"
        <<
        Default
        >>
        Bottom
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={'block': KeepBlockSpec(start='<<', end='>>')},
        keep_rest={},
        keep_header={},
        local_file_content=dedent("""\
            Top
            <<
            Custom
        """),
    )

    assert result == 'Top\n<<\nDefault\n>>\nBottom\n'


def test_apply_keep_replacements_single_definition_multiple_sibling_blocks() -> None:
    template = dedent("""\
        ## repolish-keep-block[single-block-definition]: start="<!-- start -->" end="<!-- end -->"
        <!-- start -->
        default 1
        <!-- end -->
        Part of template 1
        <!-- start -->
        default 2
        <!-- end -->
        Part of template 2
        <!-- start -->
        default 3
        <!-- end -->
        done
    """)

    local_content = dedent("""\
        <!-- start -->
        custom 1
        <!-- end -->
        Part of template 1
        <!-- start -->
        custom 2
        <!-- end -->
        Part of template 2
        <!-- start -->
        custom 3
        <!-- end -->
        done
    """)

    result = replace_text(template, local_content)

    assert result == local_content


def test_apply_keep_replacements_multiple_sibling_blocks_same_markers() -> None:
    template = dedent("""\
        ## repolish-keep-block[custom-1]: start="<!-- start -->" end="<!-- end -->"
        <!-- start -->
        default 1
        <!-- end -->
        Part of template 1
        ## repolish-keep-block[custom-2]: start="<!-- start -->" end="<!-- end -->"
        <!-- start -->
        default 2
        <!-- end -->
        Part of template 2
        ## repolish-keep-block[custom-3]: start="<!-- start -->" end="<!-- end -->"
        <!-- start -->
        default 3
        <!-- end -->
        done
    """)

    local_content = dedent("""\
        <!-- start -->
        custom 1
        <!-- end -->
        Part of template 1
        <!-- start -->
        custom 2
        <!-- end -->
        Part of template 2
        <!-- start -->
        custom 3
        <!-- end -->
        done
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={
            'custom-1': KeepBlockSpec(
                start='<!-- start -->',
                end='<!-- end -->',
            ),
            'custom-2': KeepBlockSpec(
                start='<!-- start -->',
                end='<!-- end -->',
            ),
            'custom-3': KeepBlockSpec(
                start='<!-- start -->',
                end='<!-- end -->',
            ),
        },
        keep_rest={},
        keep_header={},
        local_file_content=local_content,
    )

    assert result == local_content


def test_apply_keep_block_with_indented_markers_in_local_file() -> None:
    """Test that keep-block markers work when indented in local file.

    This is a regression test for a bug where markers at 3+ levels of
    indentation were not matched because the code required exact line matches.
    The start/end markers in the local file should match even when indented.
    """
    template = dedent("""\
        <div>
          ## repolish-keep-block[custom]: start="<!-- start -->" end="<!-- end -->"
          <!-- start -->
          Default content
          <!-- end -->
        </div>
    """)

    # Local file has markers at 4 spaces indentation (2 levels)
    local_content = dedent("""\
        <div>
          <!-- start -->
          Custom content
          <!-- end -->
        </div>
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={
            'custom': KeepBlockSpec(
                start='<!-- start -->',
                end='<!-- end -->',
            ),
        },
        keep_rest={},
        keep_header={},
        local_file_content=local_content,
    )

    # Should preserve local content with its indentation
    assert result == local_content


def test_apply_keep_block_with_deeply_indented_markers() -> None:
    """Test keep-block with markers at 3+ levels of indentation.

    This tests the specific bug where deeply indented markers (e.g., inside
    YAML nested structures) fail to match because the marker comparison
    requires exact line content match.
    """
    template = dedent("""\
        jobs:
          build:
            steps:
              ## repolish-keep-block[steps]: start="- name: custom" end="# end-custom"
              - name: custom
                run: default
              # end-custom
            done
    """)

    # Local file has deeply indented markers (8 spaces = 4 levels)
    local_content = dedent("""\
        jobs:
          build:
            steps:
              - name: custom
                run: echo "custom"
              # end-custom
            done
    """)

    result = apply_keep_replacements(
        template,
        keep_blocks={
            'steps': KeepBlockSpec(
                start='- name: custom',
                end='# end-custom',
            ),
        },
        keep_rest={},
        keep_header={},
        local_file_content=local_content,
    )

    # Should preserve local content with its indentation
    assert result == local_content


def test_apply_keep_block_tolerates_trailing_whitespace() -> None:
    """Test that keep-block markers tolerate trailing whitespace.

    This is a regression test for editors that may add trailing spaces.
    The marker comparison strips both leading and trailing whitespace.
    """
    template = dedent("""\
        <div>
          ## repolish-keep-block[custom]: start="<!-- start -->" end="<!-- end -->"
          <!-- start -->
          Default content
          <!-- end -->
        </div>
    """)

    # Local file has trailing spaces after markers (simulating editor behavior)
    local_content = '<div>\n  <!-- start -->   \n  Custom content\n  <!-- end -->  \n</div>\n'

    result = apply_keep_replacements(
        template,
        keep_blocks={
            'custom': KeepBlockSpec(
                start='<!-- start -->',
                end='<!-- end -->',
            ),
        },
        keep_rest={},
        keep_header={},
        local_file_content=local_content,
    )

    # Should preserve local content including its trailing whitespace
    assert result == local_content
