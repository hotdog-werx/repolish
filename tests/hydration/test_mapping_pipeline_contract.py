from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from repolish.hydration.application import apply_generated_output
from repolish.hydration.comparison import check_generated_output
from repolish.hydration.mapping_resolution import MappingResolution, resolve_mappings
from repolish.hydration.staging import preprocess_templates
from repolish.providers import SessionBundle, TemplateMapping

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@dataclass
class TCase:
    name: str
    mappings: dict[str, str | TemplateMapping]
    promoted_mappings: dict[str, str | TemplateMapping]
    source_name: str
    dest_name: str


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='regular_mapping_lookup',
            mappings={'dest.txt': 'source.txt'},
            promoted_mappings={},
            source_name='source.txt',
            dest_name='dest.txt',
        ),
        TCase(
            name='promoted_mapping_lookup',
            mappings={},
            promoted_mappings={'.github/workflows/ci.yml': '_repolish.ci.yml'},
            source_name='_repolish.ci.yml',
            dest_name='.github/workflows/ci.yml',
        ),
    ],
    ids=lambda c: c.name,
)
def test_contract_preprocess_uses_source_to_dest_resolution(case: TCase, tmp_path: Path) -> None:
    setup_input = tmp_path / '_' / 'stage'
    staged = setup_input / 'repolish' / case.source_name
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(
        '## repolish-regex[value]: value:\\s*(.+)\nvalue: default\n',
        encoding='utf-8',
    )

    base_dir = tmp_path / 'project'
    (base_dir / case.dest_name).parent.mkdir(parents=True, exist_ok=True)
    (base_dir / case.dest_name).write_text('value: from-local\n', encoding='utf-8')

    providers = SessionBundle(
        file_mappings=case.mappings,
        promoted_file_mappings=case.promoted_mappings,
    )

    expected = resolve_mappings(providers).source_to_dest
    assert expected[case.source_name] == case.dest_name

    preprocess_templates(setup_input, providers, base_dir)

    updated = staged.read_text(encoding='utf-8')
    assert 'value: from-local' in updated
    assert 'repolish-regex' not in updated


def test_contract_apply_and_check_share_skip_sets(tmp_path: Path) -> None:
    setup_output = tmp_path / 'render'
    out_root = setup_output / 'repolish'
    out_root.mkdir(parents=True)

    (out_root / 'auto.txt').write_text('auto-new\n', encoding='utf-8')
    (out_root / 'suppressed.txt').write_text('suppressed-new\n', encoding='utf-8')
    (out_root / 'create-only.txt').write_text('create-only-new\n', encoding='utf-8')
    (out_root / 'mapped-source.txt').write_text('mapped-new\n', encoding='utf-8')

    base_dir = tmp_path / 'project'
    base_dir.mkdir()
    (base_dir / 'create-only.txt').write_text('keep-existing\n', encoding='utf-8')
    (base_dir / 'delete-me.txt').write_text('remove\n', encoding='utf-8')

    providers = SessionBundle(
        file_mappings={
            'mapped-dest.txt': TemplateMapping(source_template='mapped-source.txt'),
        },
        paused_files=frozenset({'mapped-dest.txt'}),
        suppressed_sources={'suppressed.txt'},
        create_only_files=[Path('create-only.txt')],
        delete_files=[Path('delete-me.txt')],
    )

    resolution = resolve_mappings(providers)
    assert resolution.mapped_sources == {'mapped-source.txt'}
    assert resolution.paused_dests == frozenset({'mapped-dest.txt'})
    assert resolution.suppressed_sources == {'suppressed.txt'}
    assert resolution.create_only_dests == {'create-only.txt'}
    assert resolution.delete_dests == {'delete-me.txt'}

    diffs = check_generated_output(setup_output, providers, base_dir)
    diff_paths = {path for path, _ in diffs}

    assert 'auto.txt' in diff_paths
    assert 'suppressed.txt' not in diff_paths
    assert 'create-only.txt' not in diff_paths
    assert 'mapped-source.txt' not in diff_paths
    assert 'mapped-dest.txt' not in diff_paths
    assert 'delete-me.txt' in diff_paths

    status = apply_generated_output(setup_output, providers, base_dir)

    assert status['auto.txt'] == 'written'
    assert status['delete-me.txt'] == 'deleted'
    assert 'suppressed.txt' not in status
    assert 'create-only.txt' not in status
    assert 'mapped-source.txt' not in status
    assert 'mapped-dest.txt' not in status
    assert not (base_dir / 'mapped-dest.txt').exists()


def test_contract_stages_are_wired_to_resolver(mocker: 'MockerFixture', tmp_path: Path) -> None:
    setup_input = tmp_path / '_' / 'stage'
    staged = setup_input / 'repolish' / 'source.txt'
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(
        '## repolish-regex[value]: value:\\s*(.+)\nvalue: default\n',
        encoding='utf-8',
    )

    setup_output = tmp_path / 'render'
    out_root = setup_output / 'repolish'
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / 'skip-me.txt').write_text('from-render\n', encoding='utf-8')

    base_dir = tmp_path / 'project'
    (base_dir / 'patched-dest.txt').parent.mkdir(parents=True, exist_ok=True)
    (base_dir / 'patched-dest.txt').write_text('value: patched\n', encoding='utf-8')

    providers = SessionBundle()

    mock_resolution = MappingResolution(
        source_to_dest={'source.txt': 'patched-dest.txt'},
        dest_to_source={},
        regular_mappings={},
        promoted_mappings={},
        mapped_sources={'skip-me.txt'},
        regular_dests=set(),
        promoted_dests=set(),
        paused_dests=frozenset(),
        suppressed_sources=set(),
        create_only_dests=set(),
        delete_dests=set(),
    )

    mocker.patch(
        'repolish.hydration.staging.resolve_mappings',
        return_value=mock_resolution,
    )
    mocker.patch(
        'repolish.hydration.comparison.resolve_mappings',
        return_value=mock_resolution,
    )
    mocker.patch(
        'repolish.hydration.application.resolve_mappings',
        return_value=mock_resolution,
    )

    preprocess_templates(setup_input, providers, base_dir)
    updated = staged.read_text(encoding='utf-8')
    assert 'value: patched' in updated

    diffs = check_generated_output(setup_output, providers, base_dir)
    assert diffs == []

    status = apply_generated_output(setup_output, providers, base_dir)
    assert status == {}
