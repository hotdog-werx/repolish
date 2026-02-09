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
    expected_target_dir: str | None
    expected_templates_dir: str | None = None
    expected_library_name: str | None = None


@pytest.mark.parametrize(
    'case',
    [
        LoadProviderInfoCase(
            name='valid_info_all_fields',
            info_content="""{"target_dir": ".repolish/codeguide/resources",
"source_dir": "/fake/source/codeguide",
"templates_dir": "templates",
"library_name": "codeguide"}""",
            provider_alias='base',
            expected_target_dir='.repolish/codeguide/resources',
            expected_templates_dir='templates',
            expected_library_name='codeguide',
        ),
        LoadProviderInfoCase(
            name='valid_info_required_only',
            info_content='{"target_dir": ".repolish/python-tools/res", "source_dir": "/fake/source/python-tools"}',
            provider_alias='py',
            expected_target_dir='.repolish/python-tools/res',
            expected_templates_dir=None,
            expected_library_name=None,
        ),
        LoadProviderInfoCase(
            name='file_missing',
            info_content=None,
            provider_alias='base',
            expected_target_dir=None,
        ),
        LoadProviderInfoCase(
            name='invalid_json',
            info_content='{ not valid json }',
            provider_alias='base',
            expected_target_dir=None,
        ),
        LoadProviderInfoCase(
            name='missing_required_field',
            info_content='{"templates_dir": "templates"}',
            provider_alias='base',
            expected_target_dir=None,
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

    if case.expected_target_dir is None:
        assert result is None
    else:
        assert result is not None
        assert result.target_dir == case.expected_target_dir
        assert result.templates_dir == case.expected_templates_dir
        assert result.library_name == case.expected_library_name
