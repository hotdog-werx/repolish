from pathlib import Path

from repolish.commands.apply.insertions import (
    check_registered_insertions,
    stage_registered_insertions,
)
from repolish.directives import FerriedItem, InsertZoneDeclaration
from repolish.directives.insert_zones import InsertZoneSpec
from repolish.insertions.models import InsertionBlock
from repolish.marker_kit import RegionBoundary
from repolish.providers import SessionBundle
from repolish.providers.models import FileMode, TemplateMapping


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

    setup_output = tmp_path / '.staging'
    _, _, staged_dests = stage_registered_insertions(
        providers,
        tmp_path,
        setup_output,
    )

    assert 'README.md' in staged_dests
    text = (setup_output / 'repolish' / 'README.md').read_text(encoding='utf-8')
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

    setup_output = tmp_path / '.staging'
    stage_registered_insertions(providers, tmp_path, setup_output)

    text = (setup_output / 'repolish' / 'README.md').read_text(encoding='utf-8')
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


def test_staged_source_resolution_follows_mapping_shape(tmp_path: Path) -> None:
    """Insertion staging picks base content by mapping shape.

    A resolvable mapping renders on its freshly staged source (never the
    stale project file); a delete mapping has no source to offer and a
    mapping whose source never staged both fall back to the project copy.
    """
    staged_root = tmp_path / '.staging' / 'repolish'
    staged_root.mkdir(parents=True)

    def _marked(text: str) -> str:
        # distinguishing text lives outside the markers: the insertion
        # function replaces whatever sits between them
        return f'{text}\n<!-- repolish:on:one render -->\nold\n<!-- repolish:off:one -->\n'

    # (1) mapping whose rendered source sits in the render tree
    (staged_root / 'src.txt').write_text(
        _marked('from template'),
        encoding='utf-8',
    )
    (tmp_path / 'out.txt').write_text(
        _marked('stale project'),
        encoding='utf-8',
    )
    # (2) delete mapping — no source template at all
    (tmp_path / 'del.txt').write_text(
        _marked('stale project'),
        encoding='utf-8',
    )
    # (3) mapping whose source is absent from the render tree
    (tmp_path / 'gone.txt').write_text(
        _marked('stale project'),
        encoding='utf-8',
    )

    providers = SessionBundle(
        file_insertions={
            'out.txt': {'render': lambda: 'FRESH'},
            'del.txt': {'render': lambda: 'FRESH'},
            'gone.txt': {'render': lambda: 'FRESH'},
        },
        file_mappings={
            'out.txt': 'src.txt',
            'del.txt': TemplateMapping(
                source_template=None,
                file_mode=FileMode.DELETE,
            ),
            'gone.txt': 'missing.txt',
        },
        paused_files=set(),
    )

    _, _, staged_dests = stage_registered_insertions(
        providers,
        tmp_path,
        tmp_path / '.staging',
    )

    assert staged_dests == frozenset({'out.txt', 'del.txt', 'gone.txt'})
    out = (staged_root / 'out.txt').read_text(encoding='utf-8')
    assert 'from template' in out
    assert 'stale project' not in out
    # Delete and unsourced mappings keep the project copy as the base.
    assert 'stale project' in (staged_root / 'del.txt').read_text(
        encoding='utf-8',
    )
    assert 'stale project' in (staged_root / 'gone.txt').read_text(
        encoding='utf-8',
    )
    for rel in ('out.txt', 'del.txt', 'gone.txt'):
        assert 'FRESH' in (staged_root / rel).read_text(encoding='utf-8')
