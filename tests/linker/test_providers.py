"""Tests for repolish.linker.providers — location freshness helpers."""

from pathlib import Path

import pytest

from repolish.config.models import ProviderFileInfo
from repolish.linker.providers import link_target_current


def _link(
    tmp_path: Path,
    site: Path,
) -> Path:
    """Create ``.repolish/mylib`` as a symlink to *site* and return it."""
    site.mkdir(parents=True, exist_ok=True)
    resources = tmp_path / '.repolish' / 'mylib'
    resources.parent.mkdir(parents=True, exist_ok=True)
    resources.symlink_to(site)
    return resources


def test_link_target_current_without_site_package_dir_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache that records no ``site_package_dir`` cannot be verified.

    Info written by an older repolish (or a CLI that omits the field) has no
    package location to compare against, so the link is treated as not
    current and the provider is re-registered fresh.
    """
    monkeypatch.chdir(tmp_path)
    resources = _link(tmp_path, tmp_path / 'site' / 'mylib')

    info = ProviderFileInfo(
        resources_dir=str(resources),
        provider_root='',
        site_package_dir='',
    )

    assert link_target_current(info) is False


def test_link_target_current_false_when_link_points_elsewhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A link pointing at a different directory than recorded is stale."""
    monkeypatch.chdir(tmp_path)
    recorded = tmp_path / 'site' / 'mylib'
    recorded.mkdir(parents=True)
    actual = tmp_path / 'dev' / 'mylib'
    resources = _link(tmp_path, actual)

    info = ProviderFileInfo(
        resources_dir=str(resources),
        provider_root='',
        site_package_dir=str(recorded),
    )

    assert link_target_current(info) is False
