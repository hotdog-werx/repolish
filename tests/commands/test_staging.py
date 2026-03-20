"""Tests for repolish.commands.apply.staging helpers."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish.commands.apply.staging import find_unmapped_conditional_sources
from repolish.config.models.provider import ResolvedProviderInfo


def _make_provider_info(provider_root: Path) -> ResolvedProviderInfo:
    return ResolvedProviderInfo(
        alias='myprovider',
        provider_root=provider_root,
        resources_dir=provider_root,
    )


def _write_templates(provider_root: Path, files: list[str]) -> None:
    repolish_dir = provider_root / 'repolish'
    repolish_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        p = repolish_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('content', encoding='utf-8')


@dataclass
class FindUnmappedCase:
    name: str
    templates: list[str]
    mapped_sources: set[str]
    expected_paths: list[str]


@pytest.mark.parametrize(
    'case',
    [
        FindUnmappedCase(
            name='all_mapped',
            templates=['_repolish.a.md', '_repolish.b.md', 'README.md'],
            mapped_sources={'_repolish.a.md', '_repolish.b.md'},
            expected_paths=[],
        ),
        FindUnmappedCase(
            name='one_unmapped',
            templates=['_repolish.a.md', '_repolish.b.md', 'README.md'],
            mapped_sources={'_repolish.a.md'},
            expected_paths=['_repolish.b.md'],
        ),
        FindUnmappedCase(
            name='none_mapped',
            templates=['_repolish.a.md', 'README.md'],
            mapped_sources=set(),
            expected_paths=['_repolish.a.md'],
        ),
        FindUnmappedCase(
            name='no_conditional_files',
            templates=['README.md', 'config.yml'],
            mapped_sources=set(),
            expected_paths=[],
        ),
        FindUnmappedCase(
            name='jinja_suffix_stripped',
            templates=['_repolish.a.md.jinja'],
            mapped_sources={'_repolish.a.md'},
            expected_paths=[],
        ),
        FindUnmappedCase(
            name='jinja_suffix_not_mapped',
            templates=['_repolish.a.md.jinja'],
            mapped_sources=set(),
            expected_paths=['_repolish.a.md'],
        ),
    ],
    ids=lambda c: c.name,
)
def test_find_unmapped_conditional_sources(
    case: FindUnmappedCase,
    tmp_path: Path,
) -> None:
    provider_root = tmp_path / 'provider'
    _write_templates(provider_root, case.templates)
    infos = {'myprovider': _make_provider_info(provider_root)}

    result = find_unmapped_conditional_sources(infos, case.mapped_sources)
    found_paths = [path for _, path in result]
    assert sorted(found_paths) == sorted(case.expected_paths)


def test_find_unmapped_conditional_sources_no_repolish_dir(
    tmp_path: Path,
) -> None:
    """Provider with no repolish/ dir returns empty list."""
    provider_root = tmp_path / 'provider'
    provider_root.mkdir()
    infos = {'myprovider': _make_provider_info(provider_root)}
    assert find_unmapped_conditional_sources(infos, set()) == []


def test_find_unmapped_conditional_sources_reports_alias(
    tmp_path: Path,
) -> None:
    """Each issue tuple contains the provider alias."""
    provider_root = tmp_path / 'provider'
    _write_templates(provider_root, ['_repolish.orphan.md'])
    infos = {'custom-alias': _make_provider_info(provider_root)}

    result = find_unmapped_conditional_sources(infos, set())
    assert len(result) == 1
    alias, path = result[0]
    assert alias == 'custom-alias'
    assert path == '_repolish.orphan.md'
