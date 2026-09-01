"""Grammar unification: ``repolish:<command>`` vs legacy ``repolish-<command>``.

The colon form is the current grammar; the dash form is accepted with a
deprecation warning until v2. These tests pin both: identical extraction and
processing either way, plus the single-warning-per-file contract.
"""

from textwrap import dedent
from unittest import mock

import pytest

from repolish.directives import DirectivePhase, extract_patterns, process_text

LEGACY_AND_NEW = (
    pytest.param('-', id='legacy-dash'),
    pytest.param(':', id='new-colon'),
)


GRAMMAR_CASES = (
    pytest.param(
        '## repolish-regex[version]: ^v: (.+)$',
        '## repolish:regex[version] ^v: (.+)$',
        'v: 0\n',
        '',
        id='regex',
    ),
    pytest.param(
        '## repolish-keep-block[b]: start="<<" end=">>"',
        '## repolish:keep-block[b] start="<<" end=">>"',
        '<<\nD\n>>\n',
        '',
        id='keep-block',
    ),
    pytest.param(
        '## repolish-keep-rest[t]: marker="## mine"',
        '## repolish:keep-rest[t] marker="## mine"',
        '## mine\nplaceholder\n',
        '',
        id='keep-rest',
    ),
    pytest.param(
        '## repolish-keep-header[h]: marker="## managed"',
        '## repolish:keep-header[h] marker="## managed"',
        '## managed\ncontent\n',
        '',
        id='keep-header',
    ),
    pytest.param(
        '## repolish-multiregex-block[t]: \\[tools\\]\\n([\\s\\S]*)\n'
        '[tools]\n## repolish-multiregex[t]: ^(\\w+)\\s*=\\s*"(.+)"$',
        '## repolish:multiregex-block[t] \\[tools\\]\\n([\\s\\S]*)\n'
        '[tools]\n## repolish:multiregex[t] ^(\\w+)\\s*=\\s*"(.+)"$',
        '',
        '[tools]\nruff = "0.9.0"\n',
        id='multiregex',
    ),
)


@pytest.mark.parametrize(('legacy', 'new', 'tail', 'local'), GRAMMAR_CASES)
def test_namespace_forms_extract_identically(
    legacy: str,
    new: str,
    tail: str,
    local: str,
) -> None:
    """Dash and colon spellings extract identical directive payloads."""
    legacy_patterns = extract_patterns(legacy + '\n' + tail)
    new_patterns = extract_patterns(new + '\n' + tail)
    assert new_patterns == legacy_patterns


@pytest.mark.parametrize(('legacy', 'new', 'tail', 'local'), GRAMMAR_CASES)
def test_namespace_forms_process_identically(
    legacy: str,
    new: str,
    tail: str,
    local: str,
) -> None:
    """Dash and colon spellings produce identical processed output.

    The multiregex case needs a matching local section — without one the
    unmatched-block leak quirk preserves the literal directive line, and dash
    vs colon would then differ in spelling only.
    """
    assert process_text(new + '\n' + tail, local) == process_text(
        legacy + '\n' + tail,
        local,
    )


@pytest.mark.parametrize('sep', LEGACY_AND_NEW)
def test_tag_block_namespace_forms(sep: str) -> None:
    """Tag blocks match in both spellings, including the anchors replacement."""
    template = dedent(f"""\
        Head
        ## repolish{sep}start[install]
        default
        ## repolish{sep}end[install]
        Tail
    """)
    dash_template = template.replace(f'repolish{sep}', 'repolish-')

    result = process_text(template, '')
    dash_result = process_text(dash_template, '')

    assert result == dash_result
    assert 'default' in result
    assert 'repolish' not in result


def test_process_text_mixed_families_identical_output() -> None:
    """End-to-end: regex adoption and keep-block preservation match either way."""
    new_form = dedent("""\
        ## repolish:regex[version] ^version = "(.+?)"$
        version = "0.0.0"
        ## repolish:keep-block[notes] start="<!-- s -->" end="<!-- e -->"
        <!-- s -->
        Default
        <!-- e -->
    """)
    legacy_form = dedent("""\
        ## repolish-regex[version]: ^version = "(.+?)"$
        version = "0.0.0"
        ## repolish-keep-block[notes]: start="<!-- s -->" end="<!-- e -->"
        <!-- s -->
        Default
        <!-- e -->
    """)
    local = dedent("""\
        version = "1.4.2"
        <!-- s -->
        Mine
        <!-- e -->
    """)

    result = process_text(new_form, local)
    legacy_result = process_text(legacy_form, local)

    assert result == legacy_result
    assert 'version = "1.4.2"' in result
    assert 'Mine' in result


def test_insertion_marker_passes_through_colon_directives() -> None:
    """A template may mix ``repolish:on`` insertion markers with colon directives.

    The directive is stripped and applied; the insertion marker survives the
    whole phase untouched so the insertion stage can fill it after the file is
    written.
    """
    template = dedent("""\
        ## repolish:regex[version] ^version = "(.+?)"$
        version = "0.0.0"

        <!-- repolish:on:status render-status ready -->
        <!-- repolish:off:status -->
    """)
    local = 'version = "9.9.9"\n'

    result = process_text(template, local)

    assert 'version = "9.9.9"' in result
    assert 'repolish:regex' not in result
    assert '<!-- repolish:on:status render-status ready -->' in result
    assert '<!-- repolish:off:status -->' in result


def test_legacy_dash_form_warns_once_per_file() -> None:
    """Multiple dash directives in one file produce a single warning."""
    template = dedent("""\
        ## repolish-regex[version]: ^v: (.+)$
        ## repolish-keep-rest[tail]: marker="## mine"
        ## repolish-multiregex[tools]: ^(\\w+)\\s*=\\s*"(.+)"$
        v: 0
    """)

    with mock.patch(
        'repolish.directives.definitions.logger.warning',
    ) as warning_mock:
        extract_patterns(template, source_path='templates/example.md')

    warning_mock.assert_called_once()
    assert warning_mock.call_args.args[0] == 'legacy_directive_namespace'
    assert warning_mock.call_args.kwargs['count'] == 3
    assert warning_mock.call_args.kwargs['source_path'] == 'templates/example.md'


def test_colon_form_does_not_warn() -> None:
    """The new grammar is silent."""
    template = dedent("""\
        ## repolish:regex[version] ^v: (.+)$
        ## repolish:keep-rest[tail] marker="## mine"
        ## mine
        placeholder
    """)

    with mock.patch(
        'repolish.directives.definitions.logger.warning',
    ) as warning_mock:
        extract_patterns(template)

    warning_mock.assert_not_called()


def test_after_render_extraction_does_not_repeat_the_warning() -> None:
    """The dash warning fires only on the pre-render pass, not per phase."""
    template = '## repolish-regex[version]: ^v: (.+)$\nv: 0\n'

    with mock.patch(
        'repolish.directives.definitions.logger.warning',
    ) as warning_mock:
        extract_patterns(template, phase=DirectivePhase.AFTER_RENDER)

    warning_mock.assert_not_called()
