from typing import TYPE_CHECKING, cast

import pytest

from repolish.loader.anchors import (
    process_anchors,
)
from repolish.loader.module_loader import inject_provider_instance_for_module

if TYPE_CHECKING:
    from repolish.loader.models import Provider as _ProviderBase


def test_process_anchors_callable_and_module():
    merged = {}
    # callable that returns dict
    module_dict = cast(
        'dict[str, object]',
        {'create_anchors': lambda: {'A': 'one'}},
    )
    inject_provider_instance_for_module(
        module_dict,
        'test.provider.anchors.callable',
    )
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    process_anchors(inst, {}, merged)
    assert merged['A'] == 'one'

    # module-level anchors dict
    merged2 = {}
    module2 = cast('dict[str, object]', {'anchors': {'B': 'two'}})
    inject_provider_instance_for_module(module2, 'test.provider.anchors.var')
    inst2 = cast('_ProviderBase', module2['_repolish_provider_instance'])
    process_anchors(inst2, {}, merged2)
    assert merged2['B'] == 'two'


def test_process_anchors_callable_returns_none_no_update():
    merged = {'X': 'keep'}
    module_dict = cast('dict[str, object]', {'create_anchors': lambda: None})
    inject_provider_instance_for_module(
        module_dict,
        'test.provider.anchors.none',
    )
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    process_anchors(inst, {}, merged)
    assert merged == {'X': 'keep'}


def test_process_anchors_callable_wrong_type_raises():
    module_dict = cast(
        'dict[str, object]',
        {'create_anchors': lambda: ('not', 'a', 'dict')},
    )
    inject_provider_instance_for_module(
        module_dict,
        'test.provider.anchors.bad',
    )
    inst = cast('_ProviderBase', module_dict['_repolish_provider_instance'])
    with pytest.raises(TypeError):
        process_anchors(inst, {}, {})


def test_extract_anchors_from_module_prefers_callable_then_module():
    md = cast('dict[str, object]', {'create_anchors': lambda: {'C': 'three'}})
    inject_provider_instance_for_module(md, 'test.provider.anchors.callable2')
    got = cast(
        '_ProviderBase',
        md['_repolish_provider_instance'],
    ).create_anchors(None)
    assert got == {'C': 'three'}

    md2 = cast('dict[str, object]', {'anchors': {'D': 'four'}})
    inject_provider_instance_for_module(md2, 'test.provider.anchors.var2')
    got2 = cast(
        '_ProviderBase',
        md2['_repolish_provider_instance'],
    ).create_anchors(None)
    assert got2 == {'D': 'four'}


def test_extract_anchors_from_module_missing_returns_empty():
    md = {}
    inject_provider_instance_for_module(md, 'test.provider.anchors.empty')
    assert md['_repolish_provider_instance'].create_anchors(None) == {}
