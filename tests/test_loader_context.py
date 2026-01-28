from typing import cast

import pytest
from pytest_mock import MockerFixture

from repolish.loader.context import (
    _collect_context_from_module,
    call_factory_with_context,
    collect_contexts,
    extract_context_from_module,
    extract_from_module_dict,
)


def test_call_factory_with_context_zero_one_and_error():
    def zero() -> str:
        return 'z'

    def one(ctx: dict) -> str:
        return ctx.get('x', 'no')

    def two(a: object, b: object) -> None:
        return None

    assert call_factory_with_context(zero, {}) == 'z'
    assert call_factory_with_context(one, {'x': 'y'}) == 'y'
    with pytest.raises(TypeError):
        call_factory_with_context(two, {})


def test_extract_from_module_dict_callable_returns_wrong_type_raises():
    md = cast('dict[str, object]', {'create_thing': lambda: 'not-a-dict'})
    with pytest.raises(TypeError):
        extract_from_module_dict(md, 'create_thing', expected_type=dict)


def test_extract_from_module_dict_callable_exception_propagates():
    def bad() -> None:
        msg = 'boom'
        raise RuntimeError(msg)

    md = cast('dict[str, object]', {'create_thing': bad})
    with pytest.raises(RuntimeError):
        extract_from_module_dict(md, 'create_thing')


def test_extract_context_from_module_various_cases(mocker: MockerFixture):
    # create_context callable
    md1 = cast('dict[str, object]', {'create_context': lambda: {'a': 1}})
    assert extract_context_from_module(md1) == {'a': 1}

    # module-level context
    md2 = cast('dict[str, object]', {'context': {'b': 2}})
    assert extract_context_from_module(md2) == {'b': 2}

    # missing context triggers warning and returns None
    mock_logger = mocker.patch('repolish.loader.context.logger')
    assert extract_context_from_module({}) is None
    assert mock_logger.warning.call_count >= 1


def test_collect_contexts_merges_and_passes_merged():
    # first provider returns {'a': 1}
    md1 = cast('dict[str, object]', {'create_context': lambda: {'a': 1}})

    # second provider uses merged context when called
    def second(ctx: dict) -> dict:
        return {'b': ctx['a'] + 1}

    md2 = cast('dict[str, object]', {'create_context': second})
    merged = collect_contexts([('p1', md1), ('p2', md2)])
    assert merged == {'a': 1, 'b': 2}


def test__collect_context_from_module_raises_on_bad_return():
    md = cast(
        'dict[str, object]',
        {'create_context': lambda: ['not', 'a', 'dict']},
    )
    with pytest.raises(TypeError):
        _collect_context_from_module(md, {})
