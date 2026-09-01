"""Insert-zone family: colon-grammar extraction, strip, adoption, ferry.

Zones are colon-only — there is no legacy ``repolish-insert`` dash spelling.
Filling the zone body is insertion-phase machinery and is covered in
``tests/insertions/test_zones.py``; here we pin the directive family's side.
"""

from pathlib import Path
from textwrap import dedent
from unittest import mock

import pytest

from repolish.directives import (
    DirectivePhase,
    FilePair,
    process_file,
    process_text,
    run_phase,
)
from repolish.directives import (
    insert_zones as insert_zones_module,
)
from repolish.directives.insert_zones import (
    InsertZoneDeclaration,
    extract_insert_zone_declarations,
    extract_insert_zones,
)

TEMPLATE = """\
# Project

## repolish:insert[badges] start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"
<!-- generated:badges:on my-org/my-repo style=flat -->
_default badge row._
<!-- generated:badges:off -->
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding='utf-8')
    return path


def test_extract_basic_spec() -> None:
    zones = extract_insert_zones(TEMPLATE, 'pre-render')

    spec = zones['badges']
    assert spec.boundary.start == '<!-- generated:badges:on'
    assert spec.boundary.end == '<!-- generated:badges:off -->'
    assert spec.boundary.end_regex is None
    assert spec.function is None


def test_extract_function_override() -> None:
    template = TEMPLATE.replace(
        'end="<!-- generated:badges:off -->"',
        'end="<!-- generated:badges:off -->" function="contrib:badges"',
    )

    spec = extract_insert_zones(template, 'pre-render')['badges']

    assert spec.function == 'contrib:badges'


def test_extract_end_regex_mode() -> None:
    template = TEMPLATE.replace(
        'end="<!-- generated:badges:off -->"',
        'end-regex="^<!-- generated:badges:off"',
    )

    spec = extract_insert_zones(template, 'pre-render')['badges']

    assert spec.boundary.end is None
    assert spec.boundary.end_regex == '^<!-- generated:badges:off'


def test_extract_filters_by_phase_tag() -> None:
    template = TEMPLATE.replace('repolish:insert[badges]', 'repolish:insert[badges|after-render]')

    assert extract_insert_zones(template, 'pre-render') == {}
    zones = extract_insert_zones(template, 'after-render')
    assert zones['badges'].boundary.start == '<!-- generated:badges:on'


def test_dash_spelling_is_ignored() -> None:
    """The zone family is colon-born: the v1 dash grammar never had it."""
    template = TEMPLATE.replace(
        '## repolish:insert[badges] start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"',
        '## repolish-insert[badges]: start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"',
    )

    assert extract_insert_zones(template, 'pre-render') == {}


def test_apply_strips_directive_and_keeps_region() -> None:
    processed = process_text(TEMPLATE, '')

    assert 'repolish:insert' not in processed
    assert '<!-- generated:badges:on my-org/my-repo style=flat -->' in processed
    assert '_default badge row._' in processed
    assert '<!-- generated:badges:off -->' in processed


def test_other_phase_directive_survives_until_its_phase() -> None:
    template = TEMPLATE.replace('repolish:insert[badges]', 'repolish:insert[badges|after-render]')

    pre_rendered = process_text(template, '', phase=DirectivePhase.PRE_RENDER)
    assert 'repolish:insert[badges|after-render]' in pre_rendered

    after_rendered = process_text(pre_rendered, '', phase=DirectivePhase.AFTER_RENDER)
    assert 'repolish:insert[badges|after-render]' not in after_rendered
    assert '_default badge row._' in after_rendered


def test_apply_warns_when_template_region_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = TEMPLATE.replace(
        '<!-- generated:badges:on my-org/my-repo style=flat -->\n_default badge row._\n<!-- generated:badges:off -->\n',  # noqa: E501
        '',
    )
    mock_warn = mock.MagicMock()
    monkeypatch.setattr(insert_zones_module.logger, 'warning', mock_warn)

    processed = process_text(template, '', source_path='tpl/README.md')

    assert 'repolish:insert' not in processed
    assert 'insert_zone_template_region_not_found' in str(mock_warn.call_args[0][0])


def test_local_opening_args_adopted_body_never_is() -> None:
    local = """\
# Project

<!-- generated:badges:on other/repo style=shield -->
_developer's edited body._
<!-- generated:badges:off -->
"""

    processed = process_text(TEMPLATE, dedent(local))

    # The developer's opening marker (args included) survives the re-apply…
    assert '<!-- generated:badges:on other/repo style=shield -->' in processed
    # …but the zone body resets to the template default every time.
    assert "_developer's edited body._" not in processed
    assert '_default badge row._' in processed


def test_repeated_occurrences_adopt_in_order() -> None:
    template = TEMPLATE + TEMPLATE.partition('## repolish:insert')[2]
    local = """\
<!-- generated:badges:on -->
first-default
<!-- generated:badges:off -->
<!-- generated:badges:on tuned/repo -->
second-default
<!-- generated:badges:off -->
"""

    processed = process_text(template, dedent(local))

    # Occurrence pairing: only the second opening marker's args were edited.
    assert processed.count('<!-- generated:badges:on -->') == 1
    assert '<!-- generated:badges:on tuned/repo -->' in processed


def test_process_file_ferries_declarations_with_dest(tmp_path: Path) -> None:
    template = _write(tmp_path / 'render' / 'README.md', TEMPLATE)
    local = _write(tmp_path / 'base' / 'README.md', '# Project\n')

    result = process_file(template, local, phase=DirectivePhase.PRE_RENDER)

    assert result is not None
    assert 'repolish:insert' not in result.content
    declaration = result.zone_declarations[0]
    assert declaration == InsertZoneDeclaration(
        name='badges',
        spec=declaration.spec,
        dest=str(local),
    )
    assert declaration.spec.boundary.start == '<!-- generated:badges:on'


def test_process_file_other_phase_ferries_nothing_and_leaves_line(
    tmp_path: Path,
) -> None:
    template = _write(
        tmp_path / 'render' / 'README.md',
        TEMPLATE.replace('repolish:insert[badges]', 'repolish:insert[badges|after-render]'),
    )

    result = process_file(template, None, phase=DirectivePhase.PRE_RENDER)

    assert result is not None
    assert result.zone_declarations == ()
    assert 'repolish:insert[badges|after-render]' in result.content

    _write(tmp_path / 'render' / 'README.md', result.content)
    after = process_file(template, None, phase=DirectivePhase.AFTER_RENDER)
    assert after is not None
    assert after.zone_declarations[0].name == 'badges'
    assert 'repolish:insert' not in after.content


def test_run_phase_aggregates_declarations(tmp_path: Path) -> None:
    template_a = _write(tmp_path / 'stage' / 'A.md', TEMPLATE)
    template_b = _write(tmp_path / 'stage' / 'B.md', TEMPLATE)
    local_a = _write(tmp_path / 'base' / 'A.md', '# A\n')
    local_b = _write(tmp_path / 'base' / 'B.md', '# B\n')

    summary = run_phase(
        DirectivePhase.PRE_RENDER,
        [FilePair(template_a, local_a), FilePair(template_b, local_b)],
    )

    assert sorted(summary.changed) == sorted([str(template_a), str(template_b)])
    assert {d.dest for d in summary.zone_declarations} == {
        str(local_a),
        str(local_b),
    }


def test_extract_declarations_have_no_dest_until_callers_attach_it() -> None:
    declarations = extract_insert_zone_declarations(TEMPLATE, 'pre-render')

    assert declarations[0].dest == ''
