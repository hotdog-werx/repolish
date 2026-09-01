"""The ferry contract at the file node: families ship data past the phases.

No real family ferries data yet, so these tests (and the hydration and
apply-session ferry tests) use the shared ``ferrying_family`` fixture — a
synthetic family whose hook ferries keep-block declaration names via the
real keep extractor, exercising the same registry extension point the first
real ferrying family (insertion zones) will use.
"""

from pathlib import Path

from repolish.directives import (
    DirectivePhase,
    FerriedItem,
    FilePair,
    process_file,
    run_phase,
)

_BADGES_BLOCK = '## repolish-keep-block[badges]: start="<!-- badges -->" end="<!-- /badges -->"\n'
_FOOTER_BLOCK = '## repolish-keep-block[footer]: start="<!-- footer -->" end="<!-- /footer -->"\n'


def test_process_file_ferries_declarations_with_local_dest(
    tmp_path: Path,
    ferrying_family: None,
) -> None:
    """process_file stamps the pair's local destination on every ferried payload."""
    tpl = tmp_path / 'tpl.md'
    tpl.write_text(_BADGES_BLOCK + _FOOTER_BLOCK, encoding='utf-8')
    local = tmp_path / 'dest' / 'README.md'
    local.parent.mkdir(parents=True)
    local.write_text('', encoding='utf-8')

    result = process_file(tpl, local)

    assert result is not None
    assert result.ferry == {
        'ferry-family': (
            FerriedItem(dest=str(local), payload='badges'),
            FerriedItem(dest=str(local), payload='footer'),
        ),
    }


def test_run_phase_aggregates_ferries_across_pairs(
    tmp_path: Path,
    ferrying_family: None,
) -> None:
    """PhaseResult.ferry unions every pair's items in pair order.

    A pair without a local side stamps the staged file itself as dest.
    """
    tpl_a = tmp_path / 'a.md'
    tpl_a.write_text(_BADGES_BLOCK, encoding='utf-8')
    local = tmp_path / 'README.md'
    local.write_text('', encoding='utf-8')
    tpl_b = tmp_path / 'b.md'
    tpl_b.write_text(_FOOTER_BLOCK, encoding='utf-8')

    result = run_phase(
        DirectivePhase.PRE_RENDER,
        [FilePair(tpl_a, local), FilePair(tpl_b)],
    )

    assert result.ferry == {
        'ferry-family': (
            FerriedItem(dest=str(local), payload='badges'),
            FerriedItem(dest=str(tpl_b), payload='footer'),
        ),
    }
