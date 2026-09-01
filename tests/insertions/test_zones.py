"""Zone fill: provider-branded insertion zones against a function registry.

Zone declarations arrive from the directive ferry; filling resolves a renderer
(explicit ``function`` or the zone name) and splices its output over the zone
body. Every fallback keeps the template default instead of failing the file.
"""

from repolish.directives import InsertZoneDeclaration
from repolish.directives.insert_zones import InsertZoneSpec
from repolish.insertions import (
    InsertionBlock,
    collect_disabled_entries,
    render_insertions_text,
)
from repolish.insertions.zones import collect_insert_zones, fill_insert_zones
from repolish.marker_kit import RegionBoundary


def _decl(  # noqa: PLR0913 - test fixture: each knob maps to one spec field
    name: str,
    function: str | None = None,
    *,
    start: str = '<!-- gen:badges:on',
    end: str | None = '<!-- gen:badges:off -->',
    end_regex: str | None = None,
    dest: str = '',
) -> InsertZoneDeclaration:
    if end_regex is not None:
        boundary = RegionBoundary(start=start, end_regex=end_regex)
    else:
        boundary = RegionBoundary(start=start, end=end)
    return InsertZoneDeclaration(name, InsertZoneSpec(boundary, function), dest)


TEXT = """\
# Project

<!-- gen:badges:on my-org/my-repo style=flat -->
_default badge row._
<!-- gen:badges:off -->
"""


def test_fill_known_function_replaces_body() -> None:
    def badges() -> str:
        return 'filled-badges'

    outcome = fill_insert_zones(TEXT, [_decl('badges')], {'badges': badges})

    assert 'filled-badges' in outcome.text
    assert '_default badge row._' not in outcome.text
    assert '<!-- gen:badges:on my-org/my-repo style=flat -->' in outcome.text
    assert outcome.total_blocks == 1
    assert outcome.failed_blocks == 0
    assert outcome.diagnostics == []


def test_opening_marker_args_reach_the_renderer() -> None:
    def badges(*args: str) -> str:
        return '|'.join(args)

    outcome = fill_insert_zones(TEXT, [_decl('badges')], {'badges': badges})

    # shlex-split, with the trailing comment close dropped.
    assert 'my-org/my-repo|style=flat' in outcome.text
    assert '-->' not in outcome.blocks[0].args
    assert outcome.blocks[0].args == ('my-org/my-repo', 'style=flat')


def test_quoted_args_with_spaces_split_like_markers() -> None:
    def badges(*args: str) -> str:
        return '|'.join(args)

    text = TEXT.replace('style=flat', 'style="for the badge"')
    outcome = fill_insert_zones(text, [_decl('badges')], {'badges': badges})

    assert 'my-org/my-repo|style=for the badge' in outcome.text


def test_explicit_function_wins_over_zone_name() -> None:
    def other() -> str:
        return 'from-other'

    outcome = fill_insert_zones(
        TEXT,
        [_decl('badges', 'other')],
        {'other': other},
    )

    assert 'from-other' in outcome.text
    assert outcome.blocks[0].function == 'other'


def test_qualified_function_resolves_against_alias_keys() -> None:
    def other() -> str:
        return 'via-alias-key'

    outcome = fill_insert_zones(
        TEXT,
        [_decl('badges', 'contrib:other')],
        {'contrib:other': other},
    )

    assert 'via-alias-key' in outcome.text


def test_unknown_function_keeps_default_with_diagnostic() -> None:
    outcome = fill_insert_zones(TEXT, [_decl('badges')], {})

    assert '_default badge row._' in outcome.text
    assert outcome.total_blocks == 1
    assert outcome.failed_blocks == 1
    diagnostic = outcome.diagnostics[0]
    assert diagnostic.tag == 'badges'
    assert "No renderer registered for insertion zone 'badges'" in diagnostic.message
    assert outcome.blocks[0].tag == 'badges'


def test_failing_renderer_keeps_default_with_diagnostic() -> None:
    def badges() -> str:
        msg = 'boom'
        raise ValueError(msg)

    outcome = fill_insert_zones(TEXT, [_decl('badges')], {'badges': badges})

    assert '_default badge row._' in outcome.text
    assert outcome.failed_blocks == 1
    assert outcome.diagnostics[0].message == 'boom'


def test_malformed_opening_args_keep_default_with_diagnostic() -> None:
    text = TEXT.replace('style=flat', 'style="unterminated')

    outcome = fill_insert_zones(text, [_decl('badges')], {'badges': lambda: 'x'})

    assert '_default badge row._' in outcome.text
    assert outcome.failed_blocks == 1
    assert 'malformed opening marker args' in outcome.diagnostics[0].message


def test_disabled_wrapper_returns_body_so_default_survives() -> None:
    """Providers wrap disabled renderers to return block.body — zones ride it."""

    def _render(block: InsertionBlock) -> str:
        return block.body

    _render.__repolish_disabled_functions__ = frozenset({'badges'})  # type: ignore[attr-defined]
    _render.__repolish_disabled_tags__ = frozenset()  # type: ignore[attr-defined]

    outcome = fill_insert_zones(TEXT, [_decl('badges')], {'badges': _render})

    assert '_default badge row._' in outcome.text
    assert outcome.failed_blocks == 0
    entries = collect_disabled_entries(outcome.blocks, {'badges': _render})
    assert [entry.tag for entry in entries] == ['badges']


def test_multiple_occurrences_all_filled() -> None:
    def badges(*args: str) -> str:
        return f'badges:{len(args)}'

    text = TEXT + '\n' + TEXT
    outcome = fill_insert_zones(text, [_decl('badges')], {'badges': badges})

    assert outcome.text.count('badges:2') == 2
    assert outcome.total_blocks == 2


def test_end_regex_zone_fills() -> None:
    def badges() -> str:
        return 'regex-filled'

    text = """\
<!-- gen:badges:on -->
_default._
<!-- gen:badges:off -->
next
"""
    declaration = _decl(
        'badges',
        end=None,
        end_regex='^<!-- gen:badges:off',
    )
    outcome = fill_insert_zones(text, [declaration], {'badges': badges})

    assert 'regex-filled' in outcome.text
    assert outcome.text.endswith('next\n')


def test_merge_with_write_back_counts_blocks_together() -> None:
    """render_insertions_text reports repolish:on blocks and zones as one set."""

    def badges() -> str:
        return 'z'

    def year() -> str:
        return '2026'

    text = '<!-- repolish:on:year year -->\nobsolete\n<!-- repolish:off:year -->\n' + TEXT
    registry = {'badges': badges, 'year': year}

    result, zone_blocks = render_insertions_text(
        text,
        registry,
        file_path='README.md',
        zone_declarations=[_decl('badges')],
    )

    assert result.total_blocks == 2
    assert set(result.functions) == {'year', 'badges'}
    assert len(zone_blocks) == 1
    assert '2026' in result.text
    assert '-->\nz\n<!-- gen:badges:off -->' in result.text
    assert zone_blocks[0].file_path == 'README.md'


def test_fill_with_no_declarations_is_identity() -> None:
    outcome = fill_insert_zones(TEXT, [], {})

    assert outcome.text == TEXT
    assert outcome.total_blocks == 0


def test_collect_insert_zones_groups_by_relative_dest(tmp_path) -> None:  # noqa: ANN001 - pytest tmp_path
    base = tmp_path
    abs_dest = _decl('badges', dest=str(base / 'README.md'))
    rel_dest = _decl('badges', dest='docs/GUIDE.md')
    no_dest = _decl('badges')

    grouped = collect_insert_zones([abs_dest, rel_dest, no_dest], base)

    assert sorted(grouped) == ['README.md', 'docs/GUIDE.md']
    assert grouped['README.md'][0].dest == 'README.md'

    # Declarations from both phases for the same file merge into one tuple.
    merged = collect_insert_zones(
        [_decl('badges', dest='README.md'), _decl('links', dest='README.md')],
        base,
    )
    assert [d.name for d in merged['README.md']] == ['badges', 'links']
