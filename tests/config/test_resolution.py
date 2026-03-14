from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

from repolish.config.models import (
    ProviderConfig,
    ProviderInfo,
    RepolishConfigFile,
)
from repolish.config.resolution import _resolved_from_info, resolve_config


@dataclass
class TCase:
    name: str
    exit_code: int
    provider_info_on_retry: ProviderInfo | None
    expected_aliases: list[str]


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='auto_link_succeeds',
            exit_code=0,
            provider_info_on_retry=ProviderInfo(
                resources_dir='.repolish/base',
                site_package_dir='/some/source',
            ),
            expected_aliases=['base'],
        ),
        TCase(
            name='auto_link_fails',
            exit_code=1,
            provider_info_on_retry=None,
            expected_aliases=[],
        ),
    ],
    ids=lambda c: c.name,
)
def test_auto_link_on_missing_provider(tmp_path: Path, case: TCase):
    config_file = tmp_path / 'repolish.yaml'
    config_file.touch()
    raw_config = RepolishConfigFile(
        providers={'base': ProviderConfig(cli='some-link-cli')},
    )
    raw_config.config_file = config_file

    with (
        mock.patch(
            'repolish.config.resolution.load_provider_info',
            side_effect=[None, case.provider_info_on_retry],
        ),
        mock.patch(
            'repolish.linker.process_provider',
            return_value=case.exit_code,
        ),
    ):
        result = resolve_config(raw_config)

    assert list(result.providers.keys()) == case.expected_aliases


@dataclass
class ProviderRootCase:
    name: str
    provider_root: str  # value written to ProviderInfo.provider_root
    expected_suffix: str  # expected suffix of the resolved provider_root path


@pytest.mark.parametrize(
    'case',
    [
        ProviderRootCase(
            name='explicit_provider_root',
            provider_root='.repolish/mylib/templates',
            expected_suffix='.repolish/mylib/templates',
        ),
        ProviderRootCase(
            name='empty_provider_root_uses_resources_dir',
            provider_root='',
            expected_suffix='.repolish/mylib',
        ),
    ],
    ids=lambda c: c.name,
)
def test_resolved_from_info_provider_root(
    tmp_path: Path,
    case: ProviderRootCase,
):
    """_resolved_from_info uses provider_root directly when set; falls back to resources_dir."""
    provider_info = ProviderInfo(
        resources_dir='.repolish/mylib',
        site_package_dir=str(tmp_path / 'mylib' / 'resources'),
        provider_root=case.provider_root,
    )
    provider_config = ProviderConfig(cli='mylib-link')

    result = _resolved_from_info(
        'mylib',
        provider_config,
        provider_info,
        tmp_path,
    )

    assert result.provider_root == (tmp_path / case.expected_suffix).resolve()
