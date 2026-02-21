"""Tests for create_only_files extraction functionality."""

# extractor removed; tests exercise provider API directly
from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.module_loader import inject_provider_instance_for_module
from repolish.loader.types import FileMode, TemplateMapping


def test_extract_create_only_files_from_create_function():
    """Test extracting create_only_files from create_create_only_files() function."""
    module_dict = {
        'create_create_only_files': lambda: [
            'src/package/__init__.py',
            'config.ini',
        ],
    }
    inject_provider_instance_for_module(module_dict, 'test.provider.co.func')
    inst = module_dict['_repolish_provider_instance']
    assert isinstance(inst, _ProviderBase)  # narrow for type checker
    result = []
    fm = inst.create_file_mappings({})  # type: ignore[arg-type]
    for k, v in fm.items():
        if isinstance(v, TemplateMapping) and v.file_mode == FileMode.CREATE_ONLY:
            result.append(k)
    assert result == [
        'src/package/__init__.py',
        'config.ini',
    ]


def test_extract_create_only_files_from_module_variable():
    """Test extracting create_only_files from module-level variable."""
    module_dict = {
        'create_only_files': [
            'setup.cfg',
            '.gitignore',
        ],
    }
    inject_provider_instance_for_module(module_dict, 'test.provider.co.var')
    inst = module_dict['_repolish_provider_instance']
    assert isinstance(inst, _ProviderBase)
    result = []
    fm = inst.create_file_mappings({})  # type: ignore[arg-type]
    for k, v in fm.items():
        if isinstance(v, TemplateMapping) and v.file_mode == FileMode.CREATE_ONLY:
            result.append(k)
    assert result == [
        'setup.cfg',
        '.gitignore',
    ]


def test_extract_create_only_files_empty_when_missing():
    """Test that empty list is returned when no create_only_files present."""
    module_dict = {}
    inject_provider_instance_for_module(module_dict, 'test.provider.co.empty')
    result = []
    fm = module_dict['_repolish_provider_instance'].create_file_mappings({})
    for k, v in fm.items():
        if isinstance(v, TemplateMapping) and v.file_mode == FileMode.CREATE_ONLY:
            result.append(k)
    assert result == []
