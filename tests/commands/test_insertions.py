from pathlib import Path

from repolish.commands.apply.insertions import (
    apply_registered_insertions,
    check_registered_insertions,
)
from repolish.directives import FerriedItem, InsertZoneDeclaration
from repolish.directives.insert_zones import InsertZoneSpec
from repolish.insertions.models import InsertionBlock
from repolish.marker_kit import RegionBoundary
from repolish.providers import SessionBundle


def _write_marker_file(path: Path, body: str) -> None:
    path.write_text(
        f'Header\n<!-- repolish:on:one render -->\n{body}\n<!-- repolish:off:one -->\n',
        encoding='utf-8',
    )


def _zone_decl() -> InsertZoneDeclaration:
    """A badges zone with the grammar's usual boundary.

    No dest that travels on the FerriedItem envelope.
    """
    return InsertZoneDeclaration(
        'badges',
        InsertZoneSpec(
            RegionBoundary(
                start='<!-- generated:badges:on',
                end='<!-- generated:badges:off -->',
            ),
            None,
        ),
    )


def _zone_bundle(
    target: Path,
    *,
    insertion_registry: dict,
    file_insertions: dict | None = None,
) -> SessionBundle:
    target.write_text(
        '<!-- generated:badges:on my-org/my-repo -->\n_default_\n<!-- generated:badges:off -->\n',
        encoding='utf-8',
    )
    return SessionBundle(
        file_insertions=file_insertions or {},
        insertion_registry=insertion_registry,
        ferry={
            'insert-zone': (FerriedItem(dest='README.md', payload=_zone_decl()),),
        },
        paused_files=set(),
    )


def test_zone_fills_from_session_registry_when_dest_not_allowlisted(
    tmp_path: Path,
) -> None:
    """Zones are provider-authored.

    They resolve any contributed function,
    not just the ones the provider allowlisted for developer-owned markers.
    """

    def badges(*args: str) -> str:
        return 'FILLED(' + ' '.join(args) + ')'

    providers = _zone_bundle(
        tmp_path / 'README.md',
        # The function is registered only for a different developer file.
        insertion_registry={'badges': badges},
        file_insertions={'OTHER.md': {'badges': badges}},
    )

    apply_registered_insertions(providers, tmp_path)

    text = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert 'FILLED(my-org/my-repo)' in text
    assert '_default_' not in text


def test_zone_respects_per_file_disabled_renderer_over_session_registry(
    tmp_path: Path,
) -> None:
    """A per-file config disable wins its keys.

    The zone keeps the template
    default even though the session registry can still resolve the function.
    """

    def badges(*args: str) -> str:
        return 'FILLED'

    def _disabled(block: InsertionBlock) -> str:
        return block.body

    _disabled.__repolish_disabled_functions__ = frozenset({'badges'})  # ty: ignore[unresolved-attribute]
    _disabled.__repolish_disabled_tags__ = frozenset()  # ty: ignore[unresolved-attribute]

    providers = _zone_bundle(
        tmp_path / 'README.md',
        insertion_registry={'badges': badges},
        file_insertions={'README.md': {'badges': _disabled}},
    )

    apply_registered_insertions(providers, tmp_path)

    text = (tmp_path / 'README.md').read_text(encoding='utf-8')
    assert '_default_' in text


def test_check_registered_insertions_without_staged_output_uses_rendered_diff(
    tmp_path: Path,
) -> None:
    target = tmp_path / 'README.md'
    _write_marker_file(target, '')

    providers = SessionBundle(
        file_insertions={
            'README.md': {
                'render': lambda: 'generated',
            },
        },
        paused_files=set(),
    )

    diffs = check_registered_insertions(providers, tmp_path)

    assert len(diffs) == 1
    path, diff_text = diffs[0]
    assert path == 'README.md'
    assert 'generated' in diff_text


def test_check_registered_insertions_missing_staged_file_falls_back_and_detects_no_drift(
    tmp_path: Path,
) -> None:
    target = tmp_path / 'README.md'
    _write_marker_file(target, 'generated')

    providers = SessionBundle(
        file_insertions={
            'README.md': {
                'render': lambda: 'generated',
            },
        },
        paused_files=set(),
    )

    setup_output = tmp_path / '.staging'
    (setup_output / 'repolish').mkdir(parents=True, exist_ok=True)

    diffs = check_registered_insertions(
        providers,
        tmp_path,
        setup_output=setup_output,
    )

    assert diffs == []
