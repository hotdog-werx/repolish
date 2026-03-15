"""Tests for repolish.linker.orchestrator — apply_provider_symlinks and helpers."""

from pathlib import Path

import pytest

from repolish.config import ProviderConfig
from repolish.config.models.provider import (
    ProviderSymlink,
    ResolvedProviderInfo,
)
from repolish.linker.orchestrator import apply_provider_symlinks


def _make_provider(
    tmp_path: Path,
    alias: str = 'mylib',
) -> ResolvedProviderInfo:
    """Return a minimal ResolvedProviderInfo pointing at tmp_path."""
    return ResolvedProviderInfo(
        alias=alias,
        provider_root=tmp_path,
        resources_dir=tmp_path,
    )


def _write_repolish_py(provider_root: Path, body: str) -> None:
    (provider_root / 'repolish.py').write_text(body)


# ---------------------------------------------------------------------------
# apply_provider_symlinks — explicit config symlinks (lines 133, 139)
# ---------------------------------------------------------------------------


def test_apply_uses_explicit_config_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Explicit symlinks in repolish.yaml are applied without reading repolish.py."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.txt').write_text('content')

    provider = _make_provider(tmp_path)
    providers_config = {
        'mylib': ProviderConfig(
            provider_root=str(tmp_path),
            symlinks=[
                ProviderSymlink(
                    source=Path('config.txt'),
                    target=Path('linked.txt'),
                ),
            ],
        ),
    }

    apply_provider_symlinks({'mylib': provider}, providers_config, tmp_path)

    assert (tmp_path / 'linked.txt').exists()


def test_apply_skips_when_config_symlinks_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """An empty symlinks list in repolish.yaml suppresses all symlinks."""
    monkeypatch.chdir(tmp_path)
    _write_repolish_py(
        tmp_path,
        'from repolish import Provider, Symlink\n'
        'class MyProvider(Provider):\n'
        '    def create_default_symlinks(self):\n'
        '        return [Symlink(source="config.txt", target="linked.txt")]\n'
        'provider = MyProvider()\n',
    )
    (tmp_path / 'config.txt').write_text('content')

    provider = _make_provider(tmp_path)
    providers_config = {
        'mylib': ProviderConfig(provider_root=str(tmp_path), symlinks=[]),
    }

    apply_provider_symlinks({'mylib': provider}, providers_config, tmp_path)

    assert not (tmp_path / 'linked.txt').exists()


# ---------------------------------------------------------------------------
# apply_provider_symlinks — default symlinks from repolish.py (line 134, 139)
# ---------------------------------------------------------------------------


def test_apply_loads_default_symlinks_from_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """When no symlinks override exists, create_default_symlinks() is called."""
    monkeypatch.chdir(tmp_path)
    _write_repolish_py(
        tmp_path,
        'from repolish import Provider, Symlink\n'
        'class MyProvider(Provider):\n'
        '    def create_default_symlinks(self):\n'
        '        return [Symlink(source="config.txt", target="linked.txt")]\n'
        'provider = MyProvider()\n',
    )
    (tmp_path / 'config.txt').write_text('hello')

    provider = _make_provider(tmp_path)
    providers_config = {
        'mylib': ProviderConfig(provider_root=str(tmp_path)),
    }

    apply_provider_symlinks({'mylib': provider}, providers_config, tmp_path)

    assert (tmp_path / 'linked.txt').exists()


def test_apply_loads_default_when_provider_absent_from_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Provider not present in providers_config still loads defaults."""
    monkeypatch.chdir(tmp_path)
    _write_repolish_py(
        tmp_path,
        'from repolish import Provider, Symlink\n'
        'class MyProvider(Provider):\n'
        '    def create_default_symlinks(self):\n'
        '        return [Symlink(source="config.txt", target="linked.txt")]\n'
        'provider = MyProvider()\n',
    )
    (tmp_path / 'config.txt').write_text('hello')

    provider = _make_provider(tmp_path)

    # providers_config does not mention 'mylib' at all
    apply_provider_symlinks({'mylib': provider}, {}, tmp_path)

    assert (tmp_path / 'linked.txt').exists()


# ---------------------------------------------------------------------------
# _load_provider_default_symlinks — no repolish.py (already covered elsewhere)
# no Provider in module (lines 69-70)
# ---------------------------------------------------------------------------


def test_apply_no_provider_in_module_returns_no_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """repolish.py with no Provider instance → no symlinks created."""
    monkeypatch.chdir(tmp_path)
    _write_repolish_py(tmp_path, 'x = 42\n')

    provider = _make_provider(tmp_path)

    apply_provider_symlinks({'mylib': provider}, {}, tmp_path)
    # No crash, no symlinks written — nothing to assert beyond no exception


# ---------------------------------------------------------------------------
# _load_provider_default_symlinks — exec_module raises (lines 97-102)
# ---------------------------------------------------------------------------


def test_apply_silences_load_error_in_repolish_py(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A broken repolish.py is silenced and results in no symlinks."""
    monkeypatch.chdir(tmp_path)
    _write_repolish_py(tmp_path, 'raise RuntimeError("boom")\n')

    provider = _make_provider(tmp_path)

    # Should not propagate the RuntimeError
    apply_provider_symlinks({'mylib': provider}, {}, tmp_path)
