"""Tests for snapshot update mode via REPOLISH_UPDATE_SNAPSHOTS environment variable."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish import (
    BaseContext,
    BaseInputs,
    Provider,
    TemplateMapping,
)
from repolish.providers.models.template_path import RepolishTemplatePath
from repolish.testing import ProviderTestBed, assert_snapshots


class _TestCtx(BaseContext):
    name: str = 'test'


class _TestProvider(Provider[_TestCtx, BaseInputs]):
    def create_context(self) -> _TestCtx:
        return _TestCtx()

    def create_file_mappings(
        self,
        context: _TestCtx | None = None,
    ) -> dict[str, str | TemplateMapping | None]:
        return {'output.txt': 'output.txt.jinja'}


@pytest.fixture
def provider_templates(tmp_path: Path) -> tuple[Path, Path]:
    """Create provider with template. Returns (templates_root, snapshot_dir)."""
    templates = tmp_path / 'resources' / 'templates' / 'repolish'
    templates.mkdir(parents=True)
    (templates / 'output.txt.jinja').write_text('Hello {{ name }}!')
    return tmp_path / 'resources' / 'templates', tmp_path / 'snapshots'


@pytest.fixture
def test_provider_bed(provider_templates: tuple[Path, Path]) -> ProviderTestBed:
    """Create ProviderTestBed for _TestProvider."""
    templates_root, _ = provider_templates
    return ProviderTestBed(_TestProvider, templates_root=templates_root)


def test_update_mode_creates_missing_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    test_provider_bed: ProviderTestBed,
    provider_templates: tuple[Path, Path],
) -> None:
    """Test that update mode creates snapshots when they don't exist."""
    _, snapshot_dir = provider_templates

    rendered = test_provider_bed.render_all()

    # With update mode, should create snapshots without raising
    monkeypatch.setenv('REPOLISH_UPDATE_SNAPSHOTS', '1')
    assert_snapshots(rendered, snapshot_dir)

    # Verify snapshot was created
    snap_file = snapshot_dir / 'output.txt'
    assert snap_file.exists()
    assert snap_file.read_text() == 'Hello test!'


def test_update_mode_updates_changed_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    test_provider_bed: ProviderTestBed,
    provider_templates: tuple[Path, Path],
) -> None:
    """Test that update mode overwrites snapshots when content changes."""
    templates_root, snapshot_dir = provider_templates
    snapshot_dir.mkdir()
    (snapshot_dir / 'output.txt').write_text('Old content')

    # Change the template content
    (templates_root / 'repolish' / 'output.txt.jinja').write_text(
        'Updated: {{ name }}!',
    )
    rendered = test_provider_bed.render_all()

    # With update mode, should update the snapshot
    monkeypatch.setenv('REPOLISH_UPDATE_SNAPSHOTS', '1')
    assert_snapshots(rendered, snapshot_dir)

    # Verify snapshot was updated
    assert (snapshot_dir / 'output.txt').read_text() == 'Updated: test!'


def test_update_mode_parameter(tmp_path: Path) -> None:
    """Test that update=True parameter works without environment variable."""
    snapshot_dir = tmp_path / 'snapshots'
    rendered = {'test.txt': 'content'}

    # Should create snapshot without raising
    assert_snapshots(rendered, snapshot_dir, update=True)

    assert (snapshot_dir / 'test.txt').exists()
    assert (snapshot_dir / 'test.txt').read_text() == 'content'


@dataclass
class ResolvePathCase:
    """Test case for resolve_source_path tests."""

    name: str
    files: dict[str, str]  # filename -> content
    query: str
    expected_name: str | None  # expected resolved file name or None
    expected_content: str | None = None  # optional content check


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Create templates directory."""
    templates = tmp_path / 'templates'
    templates.mkdir()
    return templates


@pytest.mark.parametrize(
    'case',
    [
        ResolvePathCase(
            name='with_jinja',
            files={'README.md.jinja': 'content'},
            query='README.md',
            expected_name='README.md.jinja',
        ),
        ResolvePathCase(
            name='without_jinja',
            files={'README.md': 'content'},
            query='README.md',
            expected_name='README.md',
        ),
        ResolvePathCase(
            name='prefers_exact_match',
            files={'README.md': 'no jinja', 'README.md.jinja': 'jinja content'},
            query='README.md',
            expected_name='README.md',
            expected_content='no jinja',
        ),
        ResolvePathCase(
            name='with_jinja_specified',
            files={'README.md': 'content'},
            query='README.md.jinja',
            expected_name='README.md',
        ),
        ResolvePathCase(
            name='not_found',
            files={},
            query='nonexistent.txt',
            expected_name=None,
        ),
    ],
)
def test_resolve_source_path(
    templates_dir: Path,
    case: ResolvePathCase,
) -> None:
    """Test resolve_source_path with various file configurations."""
    # Create test files
    for filename, content in case.files.items():
        (templates_dir / filename).write_text(content)

    tpl = RepolishTemplatePath.from_string(case.query)
    resolved = tpl.resolve_source_path(templates_dir)

    if case.expected_name is None:
        assert resolved is None
    else:
        assert resolved is not None
        assert resolved.name == case.expected_name
        if case.expected_content is not None:
            assert resolved.read_text() == case.expected_content
