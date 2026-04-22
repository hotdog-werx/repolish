"""Tests for map_folder helper."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish import FileMode, TemplateMapping, map_folder


def _write(base: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('content', encoding='utf-8')


@dataclass
class MapFolderCase:
    name: str
    files: list[str]
    dest_dir: str
    source_dir: str
    expected: dict[str, str]


@pytest.mark.parametrize(
    'case',
    [
        MapFolderCase(
            name='flat_files',
            files=['ci.yml', 'dependabot.yml'],
            dest_dir='.github',
            source_dir='_repolish.ci.github',
            expected={
                '.github/ci.yml': '_repolish.ci.github/ci.yml',
                '.github/dependabot.yml': '_repolish.ci.github/dependabot.yml',
            },
        ),
        MapFolderCase(
            name='nested_files',
            files=['workflows/ci.yml', 'dependabot.yml'],
            dest_dir='.github',
            source_dir='_repolish.ci.github',
            expected={
                '.github/workflows/ci.yml': '_repolish.ci.github/workflows/ci.yml',
                '.github/dependabot.yml': '_repolish.ci.github/dependabot.yml',
            },
        ),
        MapFolderCase(
            name='empty_dest_dir',
            files=['ci.yml'],
            dest_dir='',
            source_dir='_repolish.ci.gitlab',
            expected={
                'ci.yml': '_repolish.ci.gitlab/ci.yml',
            },
        ),
        MapFolderCase(
            name='jinja_suffix_stripped_from_dest',
            files=['ci.yml.jinja'],
            dest_dir='.github',
            source_dir='_repolish.ci.github',
            expected={
                '.github/ci.yml': '_repolish.ci.github/ci.yml.jinja',
            },
        ),
    ],
    ids=lambda c: c.name,
)
def test_map_folder_plain_strings(case: MapFolderCase, tmp_path: Path) -> None:
    tpl = tmp_path / 'repolish'
    _write(tpl, *[f'{case.source_dir}/{f}' for f in case.files])
    result = map_folder(case.dest_dir, case.source_dir, tpl)
    assert result == case.expected


def test_map_folder_missing_source_dir_returns_empty(tmp_path: Path) -> None:
    tpl = tmp_path / 'repolish'
    tpl.mkdir()
    result = map_folder('.github', '_repolish.ci.github', tpl)
    assert result == {}


def test_map_folder_with_file_mode_returns_template_mappings(
    tmp_path: Path,
) -> None:
    tpl = tmp_path / 'repolish'
    _write(tpl, '_repolish.ci.github/ci.yml')
    result = map_folder(
        '.github',
        '_repolish.ci.github',
        tpl,
        file_mode=FileMode.CREATE_ONLY,
    )
    assert result == {
        '.github/ci.yml': TemplateMapping(
            '_repolish.ci.github/ci.yml',
            file_mode=FileMode.CREATE_ONLY,
        ),
    }


def test_map_folder_with_extra_context_returns_template_mappings(
    tmp_path: Path,
) -> None:
    tpl = tmp_path / 'repolish'
    _write(tpl, '_repolish.ci.github/ci.yml')
    ctx = {'env': 'prod'}
    result = map_folder(
        '.github',
        '_repolish.ci.github',
        tpl,
        extra_context=ctx,
    )
    assert result == {
        '.github/ci.yml': TemplateMapping(
            '_repolish.ci.github/ci.yml',
            extra_context=ctx,
        ),
    }
