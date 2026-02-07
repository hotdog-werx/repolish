"""Tests for provider configuration in repolish config."""

from pathlib import Path

from repolish.config import (
    ProviderConfig,
    ProviderSymlink,
    load_config,
)


def test_provider_config_minimal():
    """Test minimal provider configuration."""
    provider = ProviderConfig(link='mylib-link')

    assert provider.link == 'mylib-link'
    assert provider.templates_dir == 'templates'  # default
    assert provider.symlinks == []  # default


def test_provider_config_with_symlinks():
    """Test provider configuration with symlinks."""
    provider = ProviderConfig(
        link='codeguide-link',
        templates_dir='custom_templates',
        symlinks=[
            ProviderSymlink(
                source='configs/.editorconfig',
                target='.editorconfig',
            ),
            ProviderSymlink(source='configs/.prettierrc', target='.prettierrc'),
        ],
    )

    assert provider.link == 'codeguide-link'
    assert provider.templates_dir == 'custom_templates'
    assert len(provider.symlinks) == 2
    assert provider.symlinks[0].source == 'configs/.editorconfig'
    assert provider.symlinks[0].target == '.editorconfig'


def test_repolish_config_with_providers(tmp_path: Path):
    """Test loading config with providers."""
    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

providers_order: [codeguide, python-tools]

providers:
  codeguide:
    link: codeguide-link
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
      - source: configs/.prettierrc
        target: .prettierrc

  python-tools:
    link: python-tools-link
    templates_dir: custom_templates
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    config = load_config(config_file)

    assert config.providers_order == ['codeguide', 'python-tools']
    assert len(config.providers) == 2

    # Check codeguide provider
    codeguide = config.providers['codeguide']
    assert codeguide.link == 'codeguide-link'
    assert codeguide.templates_dir == 'templates'  # default
    assert len(codeguide.symlinks) == 2
    assert codeguide.symlinks[0].source == 'configs/.editorconfig'

    # Check python-tools provider
    python_tools = config.providers['python-tools']
    assert python_tools.link == 'python-tools-link'
    assert python_tools.templates_dir == 'custom_templates'
    assert len(python_tools.symlinks) == 0


def test_repolish_config_without_providers(tmp_path: Path):
    """Test that providers are optional."""
    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

context:
  key: value
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    config = load_config(config_file)

    assert config.providers == {}
    assert config.providers_order == []


def test_provider_symlink_model():
    """Test ProviderSymlink model validation."""
    symlink = ProviderSymlink(
        source='configs/.editorconfig',
        target='.editorconfig',
    )

    assert symlink.source == 'configs/.editorconfig'
    assert symlink.target == '.editorconfig'
