from typing import cast

import pytest

from repolish.loader.anchors import (
    extract_anchors_from_module,
    process_anchors,
)


def test_process_anchors_callable_and_module():
    merged = {}
    # callable that returns dict
    module_dict = cast(
        'dict[str, object]',
        {'create_anchors': lambda: {'A': 'one'}},
    )
    process_anchors(module_dict, {}, merged)
    assert merged['A'] == 'one'

    # module-level anchors dict
    merged2 = {}
    module2 = cast('dict[str, object]', {'anchors': {'B': 'two'}})
    process_anchors(module2, {}, merged2)
    assert merged2['B'] == 'two'


def test_process_anchors_callable_returns_none_no_update():
    merged = {'X': 'keep'}
    module_dict = cast('dict[str, object]', {'create_anchors': lambda: None})
    process_anchors(module_dict, {}, merged)
    assert merged == {'X': 'keep'}


def test_process_anchors_callable_wrong_type_raises():
    module_dict = cast(
        'dict[str, object]',
        {'create_anchors': lambda: ('not', 'a', 'dict')},
    )
    with pytest.raises(TypeError):
        process_anchors(module_dict, {}, {})


def test_extract_anchors_from_module_prefers_callable_then_module():
    md = cast('dict[str, object]', {'create_anchors': lambda: {'C': 'three'}})
    got = extract_anchors_from_module(md)
    assert got == {'C': 'three'}

    md2 = cast('dict[str, object]', {'anchors': {'D': 'four'}})
    got2 = extract_anchors_from_module(md2)
    assert got2 == {'D': 'four'}


def test_extract_anchors_from_module_missing_returns_empty():
    assert extract_anchors_from_module({}) == {}
