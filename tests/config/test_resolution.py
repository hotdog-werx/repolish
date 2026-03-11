from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

from repolish.config.models import (
    ProviderConfig,
    ProviderInfo,
    RepolishConfigFile,
)
from repolish.config.resolution import resolve_config


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
                target_dir='.repolish/base',
                source_dir='/some/source',
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
    raw_config.config_file = config_file  # type: ignore[assignment]

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
