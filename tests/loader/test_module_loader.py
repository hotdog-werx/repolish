from typing import TYPE_CHECKING, cast

from repolish.loader import module_loader
from repolish.loader.types import FileMode, TemplateMapping

if TYPE_CHECKING:
    from repolish.loader.models import Provider as _ProviderBase


def test_module_provider_adapter_wraps_module_functions():
    module_dict = {
        'provider_name': 'mod-a',
        'create_context': lambda: {'x': 1},
        'create_file_mappings': lambda _=None: {'a.txt': 'tpl'},
        'create_anchors': lambda _=None: {'A': 'v'},
        'collect_provider_inputs': lambda _a, _b, _c: {
            'mod-b': {'register': 'db'},
        },
        'finalize_context': lambda own, _b, _c, _d: {
            **own,
            'final': True,
        },
        'get_inputs_schema': lambda: None,
    }

    provider_id = 'providers/mod-a'
    module_loader.inject_provider_instance_for_module(module_dict, provider_id)

    inst = cast('_ProviderBase', module_dict.get('_repolish_provider_instance'))
    assert inst is not None
    assert inst.get_provider_name() == 'mod-a'

    # module-level wrapper was injected and returns dict
    assert callable(module_dict['create_context'])
    assert module_dict['create_context']() == {'x': 1}

    # instance methods delegate to originals
    assert cast('_ProviderBase', inst).create_context() == {'x': 1}
    assert cast('_ProviderBase', inst).create_file_mappings() == {
        'a.txt': 'tpl',
    }
    assert cast('_ProviderBase', inst).create_anchors() == {'A': 'v'}

    inputs = cast('_ProviderBase', inst).collect_provider_inputs({}, [], 0)
    assert inputs == {'mod-b': {'register': 'db'}}

    # finalize_context delegates
    assert cast('_ProviderBase', inst).finalize_context(
        {'x': 1},
        [],
        [],
        0,
    ) == {'x': 1, 'final': True}


def test_create_file_mappings_merges_legacy_lists():
    module_dict = {
        'create_file_mappings': lambda _=None: {'a.txt': 'tmpl'},
        'create_create_only_files': lambda: ['co.txt'],
        'create_delete_files': lambda: ['old.txt'],
    }
    pid = 'prov-merge'
    module_loader.inject_provider_instance_for_module(module_dict, pid)
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])

    res = inst.create_file_mappings({})

    assert res['a.txt'] == 'tmpl'
    assert isinstance(res['co.txt'], TemplateMapping)
    assert res['co.txt'].file_mode == FileMode.CREATE_ONLY
    assert isinstance(res['old.txt'], TemplateMapping)
    assert res['old.txt'].file_mode == FileMode.DELETE


def test_create_file_mappings_preserves_explicit_mappings():
    module_dict = {
        'create_file_mappings': lambda _=None: {'co.txt': 'explicit.tpl'},
        'create_create_only_files': lambda: ['co.txt', 'other.txt'],
    }
    pid = 'prov-precedence'
    module_loader.inject_provider_instance_for_module(module_dict, pid)
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])

    res = inst.create_file_mappings({})
    # explicit mapping must be preserved, not replaced by CREATE_ONLY conversion
    assert res['co.txt'] == 'explicit.tpl'
    assert isinstance(res['other.txt'], object)


def test_adapter_captures_originals_and_prevents_recursion():
    calls = []

    def create_ctx() -> dict[str, object]:
        calls.append('orig')
        return {'orig': True}

    module_dict = {'create_context': create_ctx}
    pid = 'p'

    # inject adapter (this will replace module_dict['create_context'] with a wrapper)
    module_loader.inject_provider_instance_for_module(module_dict, pid)

    # After injection the module-level create_context is the wrapper
    assert module_dict['create_context'] is not create_ctx

    # Adapter still calls the original function (captured during construction)
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    result = cast('_ProviderBase', inst).create_context()
    assert result == {'orig': True}
    assert calls == ['orig']

    # Calling the injected module-level wrapper also ends up invoking the original
    calls.clear()
    assert module_dict['create_context']() == {'orig': True}
    assert calls == ['orig']
