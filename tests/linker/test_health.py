"""Tests for repolish.linker.health — ensure_providers_ready and helpers."""

import json
from pathlib import Path

import pytest
import pytest_mock

from repolish.config import ProviderConfig, ProviderFileInfo
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
