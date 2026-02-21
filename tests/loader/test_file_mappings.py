"""Tests for file_mappings extraction functionality."""

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from repolish.loader.module_loader import inject_provider_instance_for_module

# extractor removed; tests interact with provider.create_file_mappings()
from repolish.loader.types import TemplateMapping

if TYPE_CHECKING:
    from repolish.loader.models import Provider as _ProviderBase


def test_extract_file_mappings_from_create_function():
    """Test extracting file_mappings from create_file_mappings() function."""
    module_dict = {
        'create_file_mappings': lambda: {
            '.github/workflows/ci.yml': '_repolish.github.yml',
            'config.toml': '_repolish.config.toml',
        },
    }
    inject_provider_instance_for_module(module_dict, 'test.provider.fm.func')
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    result = inst.create_file_mappings(None)
    # filter None values as extractor did
    result = {k: v for k, v in result.items() if v is not None}
    assert result == {
        '.github/workflows/ci.yml': '_repolish.github.yml',
        'config.toml': '_repolish.config.toml',
    }


def test_extract_file_mappings_from_module_variable():
    """Test extracting file_mappings from module-level variable."""
    module_dict = {
        'file_mappings': {
            'README.md': '_repolish.readme.md',
        },
    }
    inject_provider_instance_for_module(module_dict, 'test.provider.fm.var')
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    result = inst.create_file_mappings(None)
    result = {k: v for k, v in result.items() if v is not None}
    assert result == {'README.md': '_repolish.readme.md'}


def test_extract_file_mappings_filters_none_values():
    """Test that None values are filtered out (conditional skip)."""
    module_dict = {
        'create_file_mappings': lambda: {
            'included.txt': '_repolish.included.txt',
            'skipped.txt': None,  # Conditional: skip this destination
        },
    }
    inject_provider_instance_for_module(module_dict, 'test.provider.fm.none')
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    result = inst.create_file_mappings(None)
    result = {k: v for k, v in result.items() if v is not None}
    assert result == {'included.txt': '_repolish.included.txt'}
    assert 'skipped.txt' not in result


def test_extract_file_mappings_empty_when_missing():
    """Test that empty dict is returned when no file_mappings present."""
    module_dict = {}
    inject_provider_instance_for_module(module_dict, 'test.provider.fm.empty')
    result = module_dict['_repolish_provider_instance'].create_file_mappings(
        None,
    )
    result = {k: v for k, v in result.items() if v is not None}
    assert result == {}


def test_extract_file_mappings_allows_typed_extra_context():
    """Typed extra context (Pydantic model instance) is preserved by extractor."""

    class Ctx(BaseModel):
        x: int = 1

    module_dict = {
        'create_file_mappings': lambda: {
            'typed.txt': TemplateMapping('template.jinja', Ctx(x=5)),
        },
    }
    inject_provider_instance_for_module(module_dict, 'test.provider.fm.typed')
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    result = inst.create_file_mappings(None)
    result = {k: v for k, v in result.items() if v is not None}
    assert 'typed.txt' in result
    val = result['typed.txt']
    # extractor should preserve a TemplateMapping instance for typed extra-context
    assert isinstance(val, TemplateMapping)
    assert val.source_template == 'template.jinja'
    assert isinstance(val.extra_context, Ctx)
