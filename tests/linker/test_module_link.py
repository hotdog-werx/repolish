"""Tests for repolish.linker.module_link — in-process module provider registration.

A `module:` provider never spawns a subprocess: the probe locates the
installed package with `find_spec` and the link calls `link_resources`
directly. These tests use the `module_pkg` fixture (conftest) — tiny real
packages on `sys.path` — to pin the computed provider info and the linked
target, plus the failure modes.
"""

from pathlib import Path

import pytest
import pytest_mock

from repolish.config.models import ModuleProviderConfig
from repolish.exceptions import ModuleLinkError
from repolish.linker.module_link import probe_module_info, run_module_link


def test_probe_reports_the_default_layout(
    module_pkg: dict[str, Path],
    tmp_path: Path,
) -> None:
    """The probe mirrors the CLI `--info` output: target, root, package location."""
    config_dir = tmp_path / 'proj'
    info = probe_module_info(ModuleProviderConfig(name='mylib_ws'), config_dir)
    assert info.resources_dir == str(config_dir / '.repolish' / 'mylib-ws')
    assert info.provider_root == str(
        config_dir / '.repolish' / 'mylib-ws' / 'templates',
    )
    assert info.site_package_dir == str(module_pkg['resources'])
    assert info.package_name == 'mylib_ws'
    assert info.project_name == ''


def test_probe_honors_layout_overrides(
    module_pkg: dict[str, Path],
    tmp_path: Path,
) -> None:
    """Config overrides replace the default resources/provider root names."""
    custom = module_pkg['pkg_root'] / 'res'
    custom.mkdir()
    (custom / 'file.txt').write_text('content')
    config_dir = tmp_path / 'proj'
    info = probe_module_info(
        ModuleProviderConfig(
            name='mylib_ws',
            resources_dir='res',
            provider_root='tpl',
        ),
        config_dir,
    )
    assert info.site_package_dir == str(custom)
    assert info.provider_root == str(
        config_dir / '.repolish' / 'mylib-ws' / 'tpl',
    )


def test_probe_missing_module_raises(tmp_path: Path) -> None:
    with pytest.raises(ModuleLinkError, match='no_such_module_xyz'):
        probe_module_info(
            ModuleProviderConfig(name='no_such_module_xyz'),
            tmp_path,
        )


def test_probe_missing_parent_raises(tmp_path: Path) -> None:
    """A dotted name whose parent is not importable fails the same way."""
    with pytest.raises(ModuleLinkError, match='not importable'):
        probe_module_info(
            ModuleProviderConfig(name='no_such_parent_xyz.child'),
            tmp_path,
        )


def test_probe_plain_module_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """module: must name the provider package, not a bare .py module."""
    pkg_parent = tmp_path / 'modroot'
    pkg_parent.mkdir()
    (pkg_parent / 'plain.py').write_text('')
    monkeypatch.syspath_prepend(str(pkg_parent))
    with pytest.raises(ModuleLinkError, match='does not resolve to a package'):
        probe_module_info(ModuleProviderConfig(name='plain'), tmp_path)


def test_run_module_link_creates_the_target(
    module_pkg: dict[str, Path],
    tmp_path: Path,
) -> None:
    """The link materialises the resources under .repolish/<library-name>/."""
    config_dir = tmp_path / 'proj'
    info = run_module_link(
        'lib',
        ModuleProviderConfig(name='mylib_ws'),
        config_dir,
    )
    target = Path(info.resources_dir)
    assert target.is_symlink()
    assert (target / 'file.txt').read_text() == 'content'


def test_run_module_link_reuses_fresh_info(
    module_pkg: dict[str, Path],
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
) -> None:
    """A caller-provided probe result skips recomputation, like the CLI path."""
    config_dir = tmp_path / 'proj'
    fresh = probe_module_info(ModuleProviderConfig(name='mylib_ws'), config_dir)
    probe = mocker.patch('repolish.linker.module_link.probe_module_info')

    info = run_module_link(
        'lib',
        ModuleProviderConfig(name='mylib_ws'),
        config_dir,
        fresh_info=fresh,
    )

    probe.assert_not_called()
    assert info is fresh
    assert Path(info.resources_dir).is_symlink()


def test_run_module_link_missing_resources_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A package without a resources directory fails the link, not the probe."""
    pkg_parent = tmp_path / 'pkgroot'
    pkg_root = pkg_parent / 'empty_pkg'
    pkg_root.mkdir(parents=True)
    (pkg_root / '__init__.py').write_text('')
    monkeypatch.syspath_prepend(str(pkg_parent))

    with pytest.raises(FileNotFoundError, match='resources'):
        run_module_link(
            'lib',
            ModuleProviderConfig(name='empty_pkg'),
            tmp_path / 'proj',
        )
