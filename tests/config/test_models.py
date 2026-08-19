"""Tests for repolish.config.models module.

Only tests custom validation logic - Pydantic handles basic model validation.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish.config import (
    ProviderConfig,
    RepolishConfigFile,
)
from repolish.config.models import AliasRegistry, ProviderFileInfo
from repolish.config.models.provider import ProviderOverrides, ProviderSymlink
from repolish.config.resolution import resolve_config
from repolish.exceptions import ProviderConfigError


@dataclass
class ProviderConfigCase:
    name: str
    cli: str | None
    provider_root: str | None
    should_raise: bool
    resources_dir: str | None = None
    error_match: str | None = None


@pytest.mark.parametrize(
    'case',
    [
        ProviderConfigCase(
            name='requires_cli_or_provider_root',
            cli=None,
            provider_root=None,
            should_raise=True,
            error_match='Either cli or provider_root must be provided',
        ),
        ProviderConfigCase(
            name='accepts_both_cli_and_provider_root',
            cli='mylib-link',
            provider_root='./templates',
            should_raise=False,
        ),
        ProviderConfigCase(
            name='accepts_cli_only',
            cli='mylib-link',
            provider_root=None,
            should_raise=False,
        ),
        ProviderConfigCase(
            name='accepts_provider_root_only',
            cli=None,
            provider_root='./templates',
            should_raise=False,
        ),
        ProviderConfigCase(
            name='rejects_resources_dir_without_provider_root',
            cli='some-cli',
            provider_root=None,
            resources_dir='./resources',
            should_raise=True,
            error_match='resources_dir requires provider_root to be set',
        ),
    ],
    ids=lambda case: case.name,
)
def test_provider_config_validation(case: ProviderConfigCase):
    """Test ProviderConfig validation rules."""
    if case.should_raise:
        with pytest.raises(ProviderConfigError, match=case.error_match):
            ProviderConfig(
                cli=case.cli,
                provider_root=case.provider_root,
                resources_dir=case.resources_dir,
            )
    else:
        provider = ProviderConfig(
            cli=case.cli,
            provider_root=case.provider_root,
            resources_dir=case.resources_dir,
        )
        assert provider.cli == case.cli
        assert provider.provider_root == case.provider_root


@dataclass
class AliasRegistryCase:
    name: str
    file_content: str | None  # None means file doesn't exist
    expected_aliases: dict[str, str]


@pytest.mark.parametrize(
    'case',
    [
        AliasRegistryCase(
            name='missing_file',
            file_content=None,
            expected_aliases={},
        ),
        AliasRegistryCase(
            name='invalid_json',
            file_content='{ not valid json }',
            expected_aliases={},
        ),
        AliasRegistryCase(
            name='valid_aliases',
            file_content='{"aliases": {"base": "codeguide", "py": "python-tools"}}',
            expected_aliases={
                'base': 'codeguide',
                'py': 'python-tools',
            },
        ),
        AliasRegistryCase(
            name='empty_aliases',
            file_content='{"aliases": {}}',
            expected_aliases={},
        ),
    ],
    ids=lambda case: case.name,
)
def test_alias_registry_from_file(tmp_path: Path, case: AliasRegistryCase):
    """Test AliasRegistry.from_file() behavior."""
    all_providers_file = tmp_path / 'all_providers.json'
    if case.file_content is not None:
        all_providers_file.write_text(case.file_content)
    all_providers = AliasRegistry.from_file(all_providers_file)
    assert all_providers.aliases == case.expected_aliases


@dataclass
class ProviderInfoCase:
    name: str
    file_content: str | None  # None means file doesn't exist
    expected_resources_dir: str | None


@pytest.mark.parametrize(
    'case',
    [
        ProviderInfoCase(
            name='missing_file',
            file_content=None,
            expected_resources_dir=None,
        ),
        ProviderInfoCase(
            name='invalid_json',
            file_content='{ not valid json }',
            expected_resources_dir=None,
        ),
        ProviderInfoCase(
            name='missing_required_field',
            file_content='{"project_name": "mylib"}',
            expected_resources_dir=None,
        ),
        ProviderInfoCase(
            name='valid_minimal',
            file_content='{"resources_dir": ".repolish/provider1", "site_package_dir": "/fake/source/provider1"}',
            expected_resources_dir='.repolish/provider1',
        ),
        ProviderInfoCase(
            name='valid_with_optional_fields',
            file_content=(
                '{"resources_dir": ".repolish/provider1",'
                ' "site_package_dir": "/fake/source/provider1",'
                ' "project_name": "mylib"}'
            ),
            expected_resources_dir='.repolish/provider1',
        ),
    ],
    ids=lambda case: case.name,
)
def test_provider_info_from_file(tmp_path: Path, case: ProviderInfoCase):
    """Test ProviderFileInfo.from_file() behavior."""
    info_file = tmp_path / 'info.json'

    if case.file_content is not None:
        info_file.write_text(case.file_content)

    info = ProviderFileInfo.from_file(info_file)

    if case.expected_resources_dir is None:
        assert info is None
    else:
        assert info is not None
        assert info.resources_dir == case.expected_resources_dir


@dataclass
class ProviderShorthandCase:
    name: str
    providers_config: dict
    expected_cli: dict[str, str | None]  # provider_name -> expected cli value
    expected_provider_root: dict[
        str,
        str | None,
    ]  # provider_name -> expected provider_root value


@pytest.mark.parametrize(
    'case',
    [
        ProviderShorthandCase(
            name='shorthand_string_cli',
            providers_config={'base': 'codeguide-link'},
            expected_cli={'base': 'codeguide-link'},
            expected_provider_root={'base': None},
        ),
        ProviderShorthandCase(
            name='multiple_shorthand',
            providers_config={
                'base': 'codeguide-link',
                'py-tools': 'pytools-link',
            },
            expected_cli={'base': 'codeguide-link', 'py-tools': 'pytools-link'},
            expected_provider_root={'base': None, 'py-tools': None},
        ),
        ProviderShorthandCase(
            name='mixed_shorthand_and_expanded',
            providers_config={
                'base': 'codeguide-link',
                'local': {'provider_root': './templates'},
            },
            expected_cli={'base': 'codeguide-link', 'local': None},
            expected_provider_root={'base': None, 'local': './templates'},
        ),
        ProviderShorthandCase(
            name='expanded_with_cli',
            providers_config={'base': {'cli': 'codeguide-link'}},
            expected_cli={'base': 'codeguide-link'},
            expected_provider_root={'base': None},
        ),
    ],
    ids=lambda case: case.name,
)
def test_provider_shorthand_normalization(case: ProviderShorthandCase):
    """Test that provider shorthand syntax is normalized to full ProviderConfig."""
    config = RepolishConfigFile(providers=case.providers_config)

    assert len(config.providers) == len(case.expected_cli)

    for provider_name, expected_cli in case.expected_cli.items():
        assert provider_name in config.providers
        provider = config.providers[provider_name]
        assert isinstance(provider, ProviderConfig)
        assert provider.cli == expected_cli
        assert provider.provider_root == case.expected_provider_root[provider_name]


def test_provider_config_context_roundtrip(tmp_path: Path):
    """ProviderConfig should accept a `context` mapping.

    Resolution should carry it through to the runtime model.
    """
    # create a fake provider directory so that resolution will include it
    prov_dir = tmp_path / 'prov'
    prov_dir.mkdir()

    raw = RepolishConfigFile(
        providers={
            'foo': ProviderConfig(
                provider_root=str(prov_dir),
                overrides=ProviderOverrides(
                    context_merge={'a': 1},
                    context_dotted={'a': 2, 'nested.key': 'val'},
                ),
            ),
        },
    )

    tmpdir = tmp_path / 'cfg'
    tmpdir.mkdir()
    raw.config_file = tmpdir / 'repolish.yaml'
    resolved = resolve_config(raw)
    assert 'foo' in resolved.providers
    assert resolved.providers['foo'].overrides is not None
    assert resolved.providers['foo'].overrides.context_merge == {'a': 1}
    assert resolved.providers['foo'].overrides.context_dotted == {
        'a': 2,
        'nested.key': 'val',
    }


def test_provider_symlink_json_serializes_paths_as_posix():
    """ProviderSymlink._serialize_path emits posix strings for JSON output."""
    symlink = ProviderSymlink(
        source=Path('configs/.editorconfig'),
        target=Path('.editorconfig'),
    )
    data = symlink.model_dump(mode='json')
    assert data == {
        'source': 'configs/.editorconfig',
        'target': '.editorconfig',
    }


def test_provider_overrides_validator_shorthand_normalizes_to_enabled_flags() -> None:
    """Validator overrides accept both per-name toggles and file-level shortcut syntax."""
    overrides = ProviderOverrides.model_validate(
        {
            'validators': {
                'config.toml': {'lint': False, 'schema': True},
                'pyproject.toml': False,
            },
        },
    )

    assert overrides.validators == {
        'config.toml': {'lint': False, 'schema': True},
        'pyproject.toml': {'enabled': False},
    }


def test_provider_overrides_validator_full_form_is_preserved() -> None:
    """The full validator override dict is preserved without rewriting names."""
    overrides = ProviderOverrides(
        validators={
            'config.toml': {'lint': False},
            'settings.toml': {'schema': True},
        },
    )

    assert overrides.validators == {
        'config.toml': {'lint': False},
        'settings.toml': {'schema': True},
    }


def test_provider_overrides_insertions_shorthand_normalizes_to_enabled_flags() -> None:
    """Insertion overrides accept both per-function toggles and file-level shortcut syntax."""
    overrides = ProviderOverrides.model_validate(
        {
            'insertions': {
                'README.md': {'render-year': False, 'render-date': True},
                'CHANGELOG.md': False,
            },
        },
    )

    assert overrides.insertions == {
        'README.md': {'render-year': False, 'render-date': True},
        'CHANGELOG.md': {'enabled': False},
    }


def test_provider_overrides_insertions_full_form_is_preserved() -> None:
    """Insertion override dict entries are preserved with boolean normalization."""
    overrides = ProviderOverrides(
        insertions={
            'README.md': {'render-year': False},
            'docs.md': {'render-api': True},
        },
    )

    assert overrides.insertions == {
        'README.md': {'render-year': False},
        'docs.md': {'render-api': True},
    }


# Remove in V2.0: legacy top-level fields context, context_overrides, anchors are deprecated
class TestLegacyOverridesMigration:
    """Tests for migration of legacy top-level override fields to overrides container."""

    def test_migrate_context_to_context_merge(self):
        """Legacy 'context' field migrates to overrides.context_merge with deprecation warning."""
        with pytest.deprecated_call(
            match="Provider config field 'context' at top level is deprecated",
        ):
            config = ProviderConfig(
                provider_root='/test/provider',
                context={'key': 'value'},
            )
        assert config.overrides is not None
        assert config.overrides.context_merge == {'key': 'value'}

    def test_migrate_context_overrides_to_context_dotted(self):
        """Legacy 'context_overrides' field migrates to overrides.context_dotted with deprecation warning."""
        with pytest.deprecated_call(
            match="Provider config field 'context_overrides' at top level is deprecated",
        ):
            config = ProviderConfig(
                provider_root='/test/provider',
                context_overrides={'nested.key': 'value'},
            )
        assert config.overrides is not None
        assert config.overrides.context_dotted == {'nested.key': 'value'}

    def test_migrate_anchors_to_anchors(self):
        """Legacy 'anchors' field migrates to overrides.anchors with deprecation warning."""
        with pytest.deprecated_call(
            match="Provider config field 'anchors' at top level is deprecated",
        ):
            config = ProviderConfig(
                provider_root='/test/provider',
                anchors={'my_anchor': 'value'},
            )
        assert config.overrides is not None
        assert config.overrides.anchors == {'my_anchor': 'value'}

    def test_migrate_all_legacy_fields_at_once(self):
        """All three legacy fields migrate correctly in a single validation."""
        with pytest.deprecated_call():
            config = ProviderConfig(
                provider_root='/test/provider',
                context={'a': 1},
                context_overrides={'b': 2},
                anchors={'c': '3'},
            )
        assert config.overrides is not None
        assert config.overrides.context_merge == {'a': 1}
        assert config.overrides.context_dotted == {'b': 2}
        assert config.overrides.anchors == {'c': '3'}

    def test_explicit_overrides_takes_precedence_over_legacy(self):
        """When overrides.context_merge is explicitly set, legacy context is ignored."""
        # No warning should be emitted since the legacy value is not used
        # (explicit override takes precedence)
        config = ProviderConfig(
            provider_root='/test/provider',
            context={'legacy': 'value'},
            overrides=ProviderOverrides(context_merge={'explicit': 'value'}),
        )
        # Explicit overrides should win
        assert config.overrides is not None
        assert config.overrides.context_merge == {'explicit': 'value'}

    def test_legacy_fills_empty_overrides_field(self):
        """When overrides is empty dict, legacy fields populate it."""
        with pytest.deprecated_call():
            config = ProviderConfig(
                provider_root='/test/provider',
                context={'key': 'value'},
                overrides=ProviderOverrides(),
            )
        assert config.overrides is not None
        assert config.overrides.context_merge == {'key': 'value'}

    def test_no_warning_when_using_new_overrides_syntax(self):
        """Using the new overrides container does not emit deprecation warnings."""
        config = ProviderConfig(
            provider_root='/test/provider',
            overrides=ProviderOverrides(
                context_merge={'a': 1},
                context_dotted={'b': 2},
                anchors={'c': '3'},
            ),
        )
        assert config.overrides is not None
        assert config.overrides.context_merge == {'a': 1}
        assert config.overrides.context_dotted == {'b': 2}
        assert config.overrides.anchors == {'c': '3'}
