"""Registry-driven core: family ordering and Patterns compatibility views."""

from repolish.directives import Patterns, extract_patterns, strip_directives
from repolish.directives.keep import KeepPatterns
from repolish.directives.multiregex import MultiregexPatterns
from repolish.directives.registry import FAMILIES

TEMPLATE = """\
## repolish-keep-block[notes]: start="<!-- n:on -->" end="<!-- n:off -->"
<!-- n:on -->
notes default
<!-- n:off -->
## repolish-keep-rest[tail]: marker="## tail"
## tail
tail default
## repolish-regex[version]: ^version:\\s*(.+)
version: 0.0.0
## repolish-multiregex-block[mise]: (?s)\\[tools\\]\\n(.*?)(?:\\n\\[|$)
## repolish-multiregex[mise]: ^([A-Za-z]+) = \\"(.*?)\\"
[tools]
python = "3.12"
"""


def test_families_listing_is_ordered_and_complete() -> None:
    """The registry is the single place new directive families hook into."""
    assert [family.name for family in FAMILIES] == [
        'keep',
        'regex',
        'multiregex',
    ]


def test_patterns_exposes_family_paylods_by_name() -> None:
    patterns = extract_patterns(TEMPLATE)

    assert set(patterns.by_family) == {'keep', 'regex', 'multiregex'}
    assert isinstance(patterns.by_family['keep'], KeepPatterns)
    assert isinstance(patterns.by_family['regex'], dict)
    assert isinstance(patterns.by_family['multiregex'], MultiregexPatterns)


def test_patterns_flat_accessors_match_family_payloads() -> None:
    patterns = extract_patterns(TEMPLATE)

    assert patterns.keep_blocks == {
        'notes': ('<!-- n:on -->', '<!-- n:off -->', None),
    }
    assert patterns.keep_rest == {'tail': '## tail'}
    assert patterns.keep_header == {}
    assert patterns.regexes == {'version': '^version:\\s*(.+)'}
    assert patterns.multiregex_blocks == {
        'mise': '(?s)\\[tools\\]\\n(.*?)(?:\\n\\[|$)',
    }
    assert patterns.multiregexes == {'mise': '^([A-Za-z]+) = \\"(.*?)\\"'}


def test_strip_directives_removes_directive_lines_and_keeps_defaults() -> None:
    """Text API used by lint: directive lines go, template defaults stay."""
    stripped = strip_directives(TEMPLATE)

    # keep/regex directive lines strip unconditionally (pre-existing nuance:
    # multiregex lines only strip once the block matches a local file).
    assert 'repolish-keep' not in stripped
    assert 'repolish-regex' not in stripped
    assert 'notes default' in stripped
    assert 'version: 0.0.0' in stripped
    assert 'python = "3.12"' in stripped


def test_patterns_flat_accessors_are_empty_for_caller_built_instances() -> None:
    """Patterns built without extract_patterns (tag blocks only) read empty."""
    patterns = Patterns(tag_blocks={'intro': 'default'})

    assert patterns.tag_blocks == {'intro': 'default'}
    assert patterns.keep_blocks == {}
    assert patterns.keep_rest == {}
    assert patterns.keep_header == {}
    assert patterns.regexes == {}
    assert patterns.multiregex_blocks == {}
    assert patterns.multiregexes == {}
