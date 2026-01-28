from pathlib import Path
from typing import cast

import pytest

from repolish.loader.deletes import (
    _apply_raw_delete_items,
    _normalize_delete_iterable,
    extract_delete_items_from_module,
    normalize_delete_item,
    normalize_delete_items,
    process_delete_files,
)
from repolish.loader.types import Action, Decision


def test_normalize_delete_items_type_error():
    with pytest.raises(TypeError):
        normalize_delete_items(['good.txt', 123])  # type: ignore - testing bad input


def test_normalize_delete_item_and_iterable_filters_falsy():
    assert normalize_delete_item(Path('a/b.txt')) == 'a/b.txt'
    assert normalize_delete_item('c/d.txt') == 'c/d.txt'
    # iterable with empty string should be filtered out
    res = _normalize_delete_iterable(['ok.txt', ''])
    assert res == ['ok.txt']
    # empty input yields empty list
    assert _normalize_delete_iterable([]) == []


def test_extract_delete_items_from_module_with_callable():
    module_dict = cast(
        'dict[str, object]',
        {
            'create_delete_files': lambda: [Path('x.txt'), 'y/z.txt', ''],
        },
    )
    got = extract_delete_items_from_module(module_dict)
    assert 'x.txt' in got
    assert 'y/z.txt' in got
    assert '' not in got


def test_apply_raw_delete_items_history_and_fallback():
    delete_set = set()
    # raw items contain negation and explicit delete
    raw = ['!a.txt', 'b.txt']
    fallback = [Path('c.txt')]
    history: dict[str, list[Decision]] = {}
    _apply_raw_delete_items(delete_set, raw, fallback, 'prov1', history)
    assert Path('a.txt') not in delete_set
    assert Path('b.txt') in delete_set
    # provenance recorded
    assert history['a.txt'][-1].action == Action.keep
    assert history['b.txt'][-1].action == Action.delete

    # when raw empty, fallback is used
    delete_set2 = set()
    history2: dict[str, list[Decision]] = {}
    _apply_raw_delete_items(delete_set2, [], fallback, 'prov2', history2)
    assert Path('c.txt') in delete_set2
    assert history2['c.txt'][-1].action == Action.delete


def test_process_delete_files_callable_none_and_wrong_type():
    # callable returns None -> no fallback added, delete_set unchanged
    module_dict = cast(
        'dict[str, object]',
        {'create_delete_files': lambda: None},
    )
    delete_set = set()
    fallback = process_delete_files(module_dict, {}, delete_set)
    assert fallback == []
    assert delete_set == set()

    # callable returns wrong type -> TypeError
    module_bad = cast(
        'dict[str, object]',
        {'create_delete_files': lambda: 'not-a-list'},
    )
    with pytest.raises(TypeError):
        process_delete_files(module_bad, {}, set())


def test_process_delete_files_module_level_list_does_not_add_to_delete_set():
    module_dict = cast(
        'dict[str, object]',
        {'delete_files': [Path('m1.txt'), 'm2.txt']},
    )
    delete_set = set()
    fallback = process_delete_files(module_dict, {}, delete_set)
    # module-level delete_files should not produce fallback (only callable does)
    assert fallback == []
    assert delete_set == set()


def test_normalize_delete_item_raises_on_bad_type():
    with pytest.raises(TypeError):
        normalize_delete_item(123)


def test_apply_raw_delete_items_raises_on_invalid_raw_item():
    delete_set = set()
    history = {}
    with pytest.raises(TypeError):
        _apply_raw_delete_items(delete_set, [123], [], 'prov', history)


def test_normalize_delete_items_returns_paths():
    got = normalize_delete_items(['a.txt', 'b/c.txt'])
    assert got == [Path('a.txt'), Path('b/c.txt')]


def test_extract_delete_items_from_module_uses_module_level_list():
    md = cast(
        'dict[str, object]',
        {'delete_files': [Path('m1.txt'), 'm2.txt', '']},
    )
    got = extract_delete_items_from_module(md)
    assert 'm1.txt' in got
    assert 'm2.txt' in got
    assert '' not in got
