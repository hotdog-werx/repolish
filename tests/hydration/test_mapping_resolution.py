from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish.hydration.mapping_resolution import resolve_mappings
from repolish.providers import SessionBundle, TemplateMapping


@dataclass
class TCase:
    name: str
    file_mappings: dict[str, str | TemplateMapping]
    promoted_file_mappings: dict[str, str | TemplateMapping]
    expected_source_to_dest: dict[str, str]
    expected_dest_to_source: dict[str, str]


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='normalizes_jinja_suffixes_and_includes_both_mapping_sets',
            file_mappings={
                'dest-a.txt': '_repolish.dest-a.txt.jinja',
                'dest-b.txt': TemplateMapping(
                    source_template='sub/dest-b.txt.jinja',
                ),
            },
            promoted_file_mappings={
                'root/promoted.txt': TemplateMapping(
                    source_template='_repolish.promoted.txt',
                ),
            },
            expected_source_to_dest={
                '_repolish.dest-a.txt': 'dest-a.txt',
                'sub/dest-b.txt': 'dest-b.txt',
                '_repolish.promoted.txt': 'root/promoted.txt',
            },
            expected_dest_to_source={
                'dest-a.txt': '_repolish.dest-a.txt',
                'dest-b.txt': 'sub/dest-b.txt',
                'root/promoted.txt': '_repolish.promoted.txt',
            },
        ),
        TCase(
            name='promoted_mappings_override_regular_source_to_dest_lookup',
            file_mappings={
                'member/out.txt': TemplateMapping(
                    source_template='shared/source.txt',
                ),
            },
            promoted_file_mappings={
                'root/out.txt': TemplateMapping(
                    source_template='shared/source.txt',
                ),
            },
            expected_source_to_dest={
                'shared/source.txt': 'root/out.txt',
            },
            expected_dest_to_source={
                'member/out.txt': 'shared/source.txt',
                'root/out.txt': 'shared/source.txt',
            },
        ),
    ],
    ids=lambda case: case.name,
)
def test_resolve_mappings_collects_expected_source_and_dest_indexes(
    case: TCase,
) -> None:
    providers = SessionBundle(
        file_mappings=case.file_mappings,
        promoted_file_mappings=case.promoted_file_mappings,
    )

    resolved = resolve_mappings(providers)

    assert resolved.source_to_dest == case.expected_source_to_dest
    assert resolved.dest_to_source == case.expected_dest_to_source
    assert resolved.regular_mappings is providers.file_mappings
    assert resolved.promoted_mappings is providers.promoted_file_mappings
    assert resolved.mapped_sources == set(case.expected_source_to_dest)
    assert resolved.regular_dests == set(case.file_mappings)
    assert resolved.promoted_dests == set(case.promoted_file_mappings)


def test_resolve_mappings_collects_cross_pipeline_sets() -> None:
    providers = SessionBundle(
        file_mappings={
            'config.toml': TemplateMapping(
                source_template='_repolish.config.toml',
            ),
            'ignore-me.txt': TemplateMapping(source_template=None),
        },
        promoted_file_mappings={
            '.github/workflows/ci.yaml': '_repolish.ci.yaml',
        },
        paused_files=frozenset({'config.toml'}),
        suppressed_sources={'_repolish.skip.txt'},
        create_only_files=[Path('README.md')],
        delete_files=[Path('legacy.cfg')],
    )

    resolved = resolve_mappings(providers)

    assert resolved.paused_dests == frozenset({'config.toml'})
    assert resolved.suppressed_sources == {'_repolish.skip.txt'}
    assert resolved.create_only_dests == {'README.md'}
    assert resolved.delete_dests == {'legacy.cfg'}
    assert 'ignore-me.txt' not in resolved.dest_to_source
