"""Tests for repolish.linker.health — ensure_providers_ready and helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_mock

from repolish.config import ProviderConfig
from repolish.config.models import ProviderFileInfo
from repolish.config.providers import get_provider_info_path
from repolish.exceptions import ProviderNotReadyError
from repolish.linker import ensure_providers_ready, process_provider
from repolish.linker.health import ProviderReadinessResult


def test_all_ready():
    assert ProviderReadinessResult(ready=['a', 'b'], failed=[]).all_ready is True
    assert ProviderReadinessResult(ready=['a'], failed=['b']).all_ready is False


def test_static_provider_registers_and_is_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """ensure_providers_ready writes an info file for a provider_root that exists."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'my_provider'
    provider_root.mkdir()

    providers = {'lib': ProviderConfig(provider_root=str(provider_root))}
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=True)

    assert result.ready == ['lib']
    assert result.failed == []
    info_file = get_provider_info_path('lib', tmp_path)
    assert info_file.exists()
    saved = json.loads(info_file.read_text())
    assert saved['provider_root'] == str(provider_root)


def test_static_provider_defaults_resources_dir_to_provider_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """When resources_dir is omitted, it is recorded as provider_root."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'my_provider'
    provider_root.mkdir()

    providers = {'lib': ProviderConfig(provider_root=str(provider_root))}
    ensure_providers_ready(['lib'], providers, tmp_path, force=True)

    saved = json.loads(get_provider_info_path('lib', tmp_path).read_text())
    assert saved['resources_dir'] == str(provider_root)


def test_static_provider_uses_explicit_resources_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """When resources_dir is given it is resolved and recorded separately."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'my_provider'
    provider_root.mkdir()
    resources = tmp_path / 'my_resources'

    providers = {
        'lib': ProviderConfig(
            provider_root=str(provider_root),
            resources_dir=str(resources),
        ),
    }
    ensure_providers_ready(['lib'], providers, tmp_path, force=True)

    saved = json.loads(get_provider_info_path('lib', tmp_path).read_text())
    assert saved['resources_dir'] == str(resources)


def test_static_provider_root_missing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Registration fails gracefully when provider_root does not exist on disk."""
    monkeypatch.chdir(tmp_path)
    providers = {
        'lib': ProviderConfig(provider_root=str(tmp_path / 'nonexistent')),
    }
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=True)

    assert result.failed == ['lib']
    assert result.ready == []


def _write_info(
    alias: str,
    config_dir: Path,
    resources_dir: Path,
    provider_root: Path,
) -> None:
    info = ProviderFileInfo(
        resources_dir=str(resources_dir),
        provider_root=str(provider_root),
    )
    info_file = get_provider_info_path(alias, config_dir)
    info_file.parent.mkdir(parents=True, exist_ok=True)
    info_file.write_text(json.dumps(info.model_dump(mode='json')))


def test_valid_cached_info_skips_registration(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """When a valid info file is already on disk, registration is not re-run."""
    monkeypatch.chdir(tmp_path)
    resources_dir = tmp_path / 'res'
    resources_dir.mkdir()
    _write_info('lib', tmp_path, resources_dir, resources_dir)

    mock_register = mocker.patch('repolish.linker.health._register_provider')
    providers = {'lib': ProviderConfig(provider_root=str(resources_dir))}
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=False)

    mock_register.assert_not_called()
    assert result.ready == ['lib']


def test_stale_cached_info_triggers_reregistration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Stale cached paths (directories deleted) cause re-registration attempt."""
    monkeypatch.chdir(tmp_path)
    gone = tmp_path / 'gone'
    # write info pointing at a path that will not exist
    _write_info('lib', tmp_path, gone, gone)

    # provider_root in config also doesn't exist → re-registration will fail too
    providers = {'lib': ProviderConfig(provider_root=str(gone))}
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=False)

    # stale → re-registration attempted → fails because gone doesn't exist
    assert result.failed == ['lib']


def test_stale_provider_root_in_cache_triggers_reregistration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Stale provider_root (resources_dir exists, provider_root gone) re-registers."""
    monkeypatch.chdir(tmp_path)
    resources_dir = tmp_path / 'res'
    resources_dir.mkdir()
    gone_root = tmp_path / 'gone_root'
    # resources_dir exists but provider_root does not
    _write_info('lib', tmp_path, resources_dir, gone_root)

    providers = {'lib': ProviderConfig(provider_root=str(gone_root))}
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=False)

    assert result.failed == ['lib']


def test_cli_provider_success(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """ensure_providers_ready marks alias ready when CLI returns exit code 0."""
    monkeypatch.chdir(tmp_path)
    mocker.patch('repolish.linker.health.process_provider', return_value=0)

    providers = {'lib': ProviderConfig(cli='lib-link')}
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=True)

    assert result.ready == ['lib']


def test_cli_failure_falls_back_to_static(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """When CLI fails but provider_root exists, static fallback registers successfully."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'my_provider'
    provider_root.mkdir()
    mocker.patch('repolish.linker.health.process_provider', return_value=1)

    providers = {
        'lib': ProviderConfig(cli='lib-link', provider_root=str(provider_root)),
    }
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=True)

    assert result.ready == ['lib']
    assert get_provider_info_path('lib', tmp_path).exists()


def test_cli_failure_without_provider_root_fails(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """When CLI fails and there is no provider_root, the alias is recorded as failed."""
    monkeypatch.chdir(tmp_path)
    mocker.patch('repolish.linker.health.process_provider', return_value=1)

    providers = {'lib': ProviderConfig(cli='lib-link')}
    result = ensure_providers_ready(['lib'], providers, tmp_path, force=True)

    assert result.failed == ['lib']


def test_alias_not_in_providers_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """An alias in the order list but absent from the providers dict is silently skipped."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'res'
    provider_root.mkdir()

    providers = {'present': ProviderConfig(provider_root=str(provider_root))}
    result = ensure_providers_ready(
        ['present', 'ghost'],
        providers,
        tmp_path,
        force=True,
    )

    assert 'ghost' not in result.failed
    assert 'ghost' not in result.ready
    assert result.ready == ['present']


def test_strict_mode_raises_when_provider_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """strict=True raises ProviderNotReadyError if any provider cannot be registered."""
    monkeypatch.chdir(tmp_path)
    providers = {
        'lib': ProviderConfig(provider_root=str(tmp_path / 'nonexistent')),
    }

    with pytest.raises(ProviderNotReadyError, match='lib'):
        ensure_providers_ready(
            ['lib'],
            providers,
            tmp_path,
            force=True,
            strict=True,
        )


def test_strict_mode_does_not_raise_when_all_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """strict=True is a no-op when all providers register successfully."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'my_provider'
    provider_root.mkdir()

    providers = {'lib': ProviderConfig(provider_root=str(provider_root))}
    result = ensure_providers_ready(
        ['lib'],
        providers,
        tmp_path,
        force=True,
        strict=True,
    )

    assert result.all_ready


def test_process_provider_skips_when_no_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """process_provider returns 0 without running anything when cli is None."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'res'
    provider_root.mkdir()
    config = ProviderConfig(provider_root=str(provider_root))

    exit_code = process_provider('lib', config, tmp_path)

    assert exit_code == 0


def _write_cli_info(
    alias: str,
    config_dir: Path,
    resources_dir: Path,
    site_package_dir: Path,
) -> None:
    """Write a provider-info file the way a CLI provider's ``--info`` would."""
    info = ProviderFileInfo(
        resources_dir=str(resources_dir),
        provider_root='',
        site_package_dir=str(site_package_dir),
        package_name='mylib',
        project_name='mylib',
    )
    info_file = get_provider_info_path(alias, config_dir)
    info_file.parent.mkdir(parents=True, exist_ok=True)
    info_file.write_text(json.dumps(info.model_dump(mode='json')))


def _mock_probe(
    mocker: pytest_mock.MockerFixture,
    payload: dict,
) -> MagicMock:
    """Mock subprocess.run so the first call returns a ``--info`` payload."""
    mock_run = mocker.patch('subprocess.run')
    mock_info = MagicMock()
    mock_info.stdout = json.dumps(payload)
    mock_run.return_value = mock_info
    return mock_run


def test_apply_trusts_valid_cache_without_probe(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """Without verify_locations (apply), a valid cache skips the CLI entirely."""
    monkeypatch.chdir(tmp_path)
    site = (tmp_path / 'site' / 'mylib').resolve()
    site.mkdir(parents=True)
    resources = tmp_path / '.repolish' / 'mylib'
    resources.parent.mkdir(parents=True, exist_ok=True)
    resources.symlink_to(site)
    _write_cli_info('lib', tmp_path, resources, site)

    mock_run = _mock_probe(mocker, {})
    providers = {'lib': ProviderConfig(cli='mylib-link')}
    result = ensure_providers_ready(['lib'], providers, tmp_path)

    mock_run.assert_not_called()
    assert result.ready == ['lib']
    assert result.cached == ['lib']


def test_link_probe_skips_relink_when_location_unchanged(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """Repolish link probes --info; matching location means no link subprocess."""
    monkeypatch.chdir(tmp_path)
    site = (tmp_path / 'site' / 'mylib').resolve()
    site.mkdir(parents=True)
    resources = tmp_path / '.repolish' / 'mylib'
    resources.parent.mkdir(parents=True, exist_ok=True)
    resources.symlink_to(site)
    _write_cli_info('lib', tmp_path, resources, site)

    probe_payload = {
        'resources_dir': str(resources),
        'provider_root': '',
        'site_package_dir': str(site),
        'package_name': 'mylib',
        'project_name': 'mylib',
    }
    mock_run = _mock_probe(mocker, probe_payload)
    providers = {'lib': ProviderConfig(cli='mylib-link')}
    result = ensure_providers_ready(
        ['lib'],
        providers,
        tmp_path,
        verify_locations=True,
    )

    # Only the --info probe ran; the link command was skipped.
    assert mock_run.call_count == 1
    assert mock_run.call_args[0][0] == ['mylib-link', '--info']
    assert result.ready == ['lib']
    assert result.cached == ['lib']


def test_link_probe_reregisters_when_location_moved(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """A provider package that moved (dev ↔ release) is re-registered."""
    monkeypatch.chdir(tmp_path)
    old_site = (tmp_path / 'old_site' / 'mylib').resolve()
    old_site.mkdir(parents=True)
    new_site = (tmp_path / 'new_site' / 'mylib').resolve()
    new_site.mkdir(parents=True)
    resources = tmp_path / '.repolish' / 'mylib'
    resources.parent.mkdir(parents=True, exist_ok=True)
    resources.symlink_to(old_site)  # still pointing at the old location
    _write_cli_info('lib', tmp_path, resources, old_site)

    probe_payload = {
        'resources_dir': str(resources),
        'provider_root': '',
        'site_package_dir': str(new_site),
        'package_name': 'mylib',
        'project_name': 'mylib',
    }
    mock_run = mocker.patch('subprocess.run')
    mock_run.side_effect = [
        MagicMock(stdout=json.dumps(probe_payload)),
        MagicMock(),
    ]

    providers = {'lib': ProviderConfig(cli='mylib-link')}
    result = ensure_providers_ready(
        ['lib'],
        providers,
        tmp_path,
        verify_locations=True,
    )

    # Probe + actual link both ran.
    assert mock_run.call_count == 2
    assert result.ready == ['lib']
    assert result.cached == []
    saved = json.loads(get_provider_info_path('lib', tmp_path).read_text())
    assert saved['site_package_dir'] == str(new_site)


def test_link_probe_missing_link_target_reruns_link(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """Location unchanged but .repolish/<alias> is not a symlink → re-link."""
    monkeypatch.chdir(tmp_path)
    site = (tmp_path / 'site' / 'mylib').resolve()
    site.mkdir(parents=True)
    resources = tmp_path / '.repolish' / 'mylib'
    resources.mkdir(parents=True)  # plain directory, not a symlink

    _write_cli_info('lib', tmp_path, resources, site)

    probe_payload = {
        'resources_dir': str(resources),
        'provider_root': '',
        'site_package_dir': str(site),
        'package_name': 'mylib',
        'project_name': 'mylib',
    }
    mock_run = mocker.patch('subprocess.run')
    mock_run.side_effect = [
        MagicMock(stdout=json.dumps(probe_payload)),
        MagicMock(),
    ]

    providers = {'lib': ProviderConfig(cli='mylib-link')}
    result = ensure_providers_ready(
        ['lib'],
        providers,
        tmp_path,
        verify_locations=True,
    )

    assert mock_run.call_count == 2
    assert result.cached == []


def test_static_provider_unchanged_is_cached(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """A static provider whose config paths match the cache is not re-registered."""
    monkeypatch.chdir(tmp_path)
    provider_root = (tmp_path / 'my_provider').resolve()
    provider_root.mkdir()
    _write_info('lib', tmp_path, provider_root, provider_root)

    mock_register = mocker.patch('repolish.linker.health._register_provider')
    providers = {'lib': ProviderConfig(provider_root=str(provider_root))}
    result = ensure_providers_ready(['lib'], providers, tmp_path)

    mock_register.assert_not_called()
    assert result.cached == ['lib']


def test_static_provider_config_change_reregisters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Changing provider_root in repolish.yaml re-registers even without --force."""
    monkeypatch.chdir(tmp_path)
    old_root = (tmp_path / 'old_provider').resolve()
    old_root.mkdir()
    new_root = (tmp_path / 'new_provider').resolve()
    new_root.mkdir()
    _write_info(
        'lib',
        tmp_path,
        old_root,
        old_root,
    )  # cache still on the old path

    providers = {'lib': ProviderConfig(provider_root=str(new_root))}
    result = ensure_providers_ready(['lib'], providers, tmp_path)

    assert result.ready == ['lib']
    assert result.cached == []
    saved = json.loads(get_provider_info_path('lib', tmp_path).read_text())
    assert saved['provider_root'] == str(new_root)


def test_no_cache_file_registers_from_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Without a provider-info file at all, the provider registers normally."""
    monkeypatch.chdir(tmp_path)
    provider_root = tmp_path / 'my_provider'
    provider_root.mkdir()

    providers = {'lib': ProviderConfig(provider_root=str(provider_root))}
    result = ensure_providers_ready(['lib'], providers, tmp_path)  # no force, no cache

    assert result.ready == ['lib']
    assert result.cached == []
    assert get_provider_info_path('lib', tmp_path).exists()


def test_link_probe_failure_falls_back_to_registration(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """A probe that fails (CLI missing or broken) falls through to registration.

    Registration probes again inside ``run_provider_link``; when that fails
    too, the static ``provider_root`` fallback registers the provider.
    """
    monkeypatch.chdir(tmp_path)
    site = (tmp_path / 'site' / 'mylib').resolve()
    site.mkdir(parents=True)
    resources = tmp_path / '.repolish' / 'mylib'
    resources.parent.mkdir(parents=True, exist_ok=True)
    resources.symlink_to(site)
    _write_cli_info('lib', tmp_path, resources, site)

    mock_run = mocker.patch(
        'subprocess.run',
        side_effect=FileNotFoundError('mylib-link'),
    )
    providers = {
        'lib': ProviderConfig(cli='mylib-link', provider_root=str(site)),
    }
    result = ensure_providers_ready(
        ['lib'],
        providers,
        tmp_path,
        verify_locations=True,
    )

    # Probe in _probe_or_register + probe in run_provider_link, both failed.
    assert mock_run.call_count == 2
    assert result.ready == ['lib']
    assert result.cached == []
    saved = json.loads(get_provider_info_path('lib', tmp_path).read_text())
    assert saved['site_package_dir'] == ''  # static fallback: no package location
