"""Tests for repolish.config.models module.

Only tests custom validation logic - Pydantic handles basic model validation.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish.config.models import (
    AllProviders,
    ProviderConfig,
    ProviderInfo,
)


@dataclass
class ProviderConfigCase:
    name: str
    cli: str | None
    directory: str | None
    should_raise: bool
    error_match: str | None = None


@pytest.mark.parametrize(
    'case',
    [
        ProviderConfigCase(
            name='requires_cli_or_directory',
            cli=None,
            directory=None,
            should_raise=True,
            error_match='Either cli or directory must be provided',
        ),
        ProviderConfigCase(
            name='rejects_both_cli_and_directory',
            cli='mylib-link',
            directory='./templates',
            should_raise=True,
            error_match='Cannot specify both cli and directory',
        ),
        ProviderConfigCase(
            name='accepts_cli_only',
            cli='mylib-link',
            directory=None,
            should_raise=False,
        ),
        ProviderConfigCase(
            name='accepts_directory_only',
            cli=None,
            directory='./templates',
            should_raise=False,
        ),
    ],
    ids=lambda case: case.name,
)
def test_provider_config_validation(case: ProviderConfigCase):
    """Test ProviderConfig validation rules."""
    if case.should_raise:
        with pytest.raises(ValueError, match=case.error_match):
            ProviderConfig(cli=case.cli, directory=case.directory)
    else:
        provider = ProviderConfig(cli=case.cli, directory=case.directory)
        assert provider.cli == case.cli
        assert provider.directory == case.directory


@dataclass
class AllProvidersCase:
    name: str
    file_content: str | None  # None means file doesn't exist
    expected_aliases: dict[str, str]


@pytest.mark.parametrize(
    'case',
    [
        AllProvidersCase(
            name='missing_file',
            file_content=None,
            expected_aliases={},
        ),
        AllProvidersCase(
            name='invalid_json',
            file_content='{ not valid json }',
            expected_aliases={},
        ),
        AllProvidersCase(
            name='valid_aliases',
            file_content='{"aliases": {"base": "codeguide", "py": "python-tools"}}',
            expected_aliases={
                'base': 'codeguide',
                'py': 'python-tools',
            },
        ),
        AllProvidersCase(
            name='empty_aliases',
            file_content='{"aliases": {}}',
            expected_aliases={},
        ),
    ],
    ids=lambda case: case.name,
)
def test_all_providers_from_file(tmp_path: Path, case: AllProvidersCase):
    """Test AllProviders.from_file() behavior."""
    all_providers_file = tmp_path / 'all_providers.json'
    if case.file_content is not None:
        all_providers_file.write_text(case.file_content)
    all_providers = AllProviders.from_file(all_providers_file)
    assert all_providers.aliases == case.expected_aliases


@dataclass
class ProviderInfoCase:
    name: str
    file_content: str | None  # None means file doesn't exist
    expected_target_dir: str | None
    expected_templates_dir: str | None = None
    expected_library_name: str | None = None


@pytest.mark.parametrize(
    'case',
    [
        ProviderInfoCase(
            name='missing_file',
            file_content=None,
            expected_target_dir=None,
        ),
        ProviderInfoCase(
            name='invalid_json',
            file_content='{ not valid json }',
            expected_target_dir=None,
        ),
        ProviderInfoCase(
            name='missing_required_field',
            file_content='{"library_name": "mylib"}',
            expected_target_dir=None,
        ),
        ProviderInfoCase(
            name='valid_minimal',
            file_content='{"target_dir": ".repolish/provider1"}',
            expected_target_dir='.repolish/provider1',
        ),
        ProviderInfoCase(
            name='valid_with_optional_fields',
            file_content='{"target_dir": ".repolish/provider1", "templates_dir": "custom", "library_name": "mylib"}',
            expected_target_dir='.repolish/provider1',
            expected_templates_dir='custom',
            expected_library_name='mylib',
        ),
    ],
    ids=lambda case: case.name,
)
def test_provider_info_from_file(tmp_path: Path, case: ProviderInfoCase):
    """Test ProviderInfo.from_file() behavior."""
    info_file = tmp_path / 'info.json'

    if case.file_content is not None:
        info_file.write_text(case.file_content)

    info = ProviderInfo.from_file(info_file)

    if case.expected_target_dir is None:
        assert info is None
    else:
        assert info is not None
        assert info.target_dir == case.expected_target_dir
        assert info.templates_dir == case.expected_templates_dir
        assert info.library_name == case.expected_library_name
