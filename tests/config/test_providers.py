from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish.config.providers import (
    load_provider_info,
    resolve_provider_alias,
)


@dataclass
class ResolveAliasCase:
    name: str
    aliases_content: str | None  # None means file doesn't exist
    provider_alias: str
    expected_path: str | None


@pytest.mark.parametrize(
    'case',
    [
        ResolveAliasCase(
            name='alias_exists',
            aliases_content='{"aliases": {"base": "codeguide", "py": "python-tools"}}',
            provider_alias='base',
            expected_path='.repolish/codeguide',
        ),
        ResolveAliasCase(
            name='alias_not_found',
            aliases_content='{"aliases": {"base": "codeguide"}}',
            provider_alias='nonexistent',
            expected_path=None,
        ),
        ResolveAliasCase(
            name='file_missing',
            aliases_content=None,
            provider_alias='base',
            expected_path=None,
        ),
        ResolveAliasCase(
            name='empty_aliases',
            aliases_content='{"aliases": {}}',
            provider_alias='base',
            expected_path=None,
        ),
    ],
    ids=lambda case: case.name,
)
def test_resolve_provider_alias(tmp_path: Path, case: ResolveAliasCase):
    """Test resolve_provider_alias() behavior."""
    aliases_file = tmp_path / '.repolish' / '_' / '.all-providers.json'
    if case.aliases_content is not None:
        aliases_file.parent.mkdir(parents=True, exist_ok=True)
        aliases_file.write_text(case.aliases_content)

    result = resolve_provider_alias(case.provider_alias, tmp_path)
    assert result == case.expected_path


@dataclass
class LoadProviderInfoCase:
    name: str
    info_content: str | None  # None means file doesn't exist
    provider_alias: str
    expected_resources_dir: str | None


@pytest.mark.parametrize(
    'case',
    [
        LoadProviderInfoCase(
            name='valid_info_all_fields',
            info_content=(
                '{"resources_dir": ".repolish/codeguide/resources",'
                ' "site_package_dir": "/fake/source/codeguide",'
                ' "provider_root": ".repolish/codeguide/resources/templates"}'
            ),
            provider_alias='base',
            expected_resources_dir='.repolish/codeguide/resources',
        ),
        LoadProviderInfoCase(
            name='valid_info_required_only',
            info_content=(
                '{"resources_dir": ".repolish/python-tools/res", "site_package_dir": "/fake/source/python-tools"}'
            ),
            provider_alias='py',
            expected_resources_dir='.repolish/python-tools/res',
        ),
        LoadProviderInfoCase(
            name='file_missing',
            info_content=None,
            provider_alias='base',
            expected_resources_dir=None,
        ),
        LoadProviderInfoCase(
            name='invalid_json',
            info_content='{ not valid json }',
            provider_alias='base',
            expected_resources_dir=None,
        ),
        LoadProviderInfoCase(
            name='missing_required_field',
            info_content='{"site_package_dir": "/fake/source"}',
            provider_alias='base',
            expected_resources_dir=None,
        ),
    ],
    ids=lambda case: case.name,
)
def test_load_provider_info(tmp_path: Path, case: LoadProviderInfoCase):
    """Test load_provider_info() behavior."""
    info_file = tmp_path / '.repolish' / '_' / f'provider-info.{case.provider_alias}.json'
    if case.info_content is not None:
        info_file.parent.mkdir(parents=True, exist_ok=True)
        info_file.write_text(case.info_content)

    result = load_provider_info(case.provider_alias, tmp_path)

    if case.expected_resources_dir is None:
        assert result is None
    else:
        assert result is not None
        assert result.resources_dir == case.expected_resources_dir
