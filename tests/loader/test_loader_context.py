from typing import TYPE_CHECKING, cast

import pytest
from pydantic import BaseModel, field_validator
from pytest_mock import MockerFixture

from repolish.loader.context import _apply_override, apply_context_overrides
from repolish.loader.module_loader import (
    _collect_context_from_module,
    call_factory_with_context,
    collect_contexts,
    collect_contexts_with_provider_map,
    extract_from_module_dict,
    inject_provider_instance_for_module,
)
from repolish.loader.orchestrator import _apply_overrides_to_model

if TYPE_CHECKING:
    from repolish.loader.models import Provider as _ProviderBase


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
    inject_provider_instance_for_module(md1, 'test.provider.ctx.func')
    assert cast(
        '_ProviderBase',
        md1['_repolish_provider_instance'],
    ).create_context() == {'a': 1}

    # module-level context
    md2 = cast('dict[str, object]', {'context': {'b': 2}})
    inject_provider_instance_for_module(md2, 'test.provider.ctx.var')
    assert cast(
        '_ProviderBase',
        md2['_repolish_provider_instance'],
    ).create_context() == {'b': 2}

    # missing context on an adapter-backed provider returns an empty dict
    md3 = cast('dict[str, object]', {})
    inject_provider_instance_for_module(md3, 'test.provider.ctx.none')
    assert (
        cast(
            '_ProviderBase',
            md3['_repolish_provider_instance'],
        ).create_context()
        == {}
    )


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


def test_collect_contexts_with_provider_map_warns_on_none_return():
    """`create_context()` returning None emits a deprecation warning.

    DeprecationWarning but is still treated as an empty context
    (back-compat).
    """
    module_cache = [('prov-none', {'create_context': lambda: None})]

    with pytest.warns(
        DeprecationWarning,
        match=r'create_context\(\) returning None is deprecated',
    ) as record:
        merged, provider_map = collect_contexts_with_provider_map(module_cache)

    assert merged == {}
    assert provider_map['prov-none'] == {}
    assert any('create_context() returning None is deprecated' in str(w.message) for w in record)


def test_apply_context_overrides(mocker: MockerFixture):
    # include a plain object to prove that overrides only work on dict/list
    class Repo(BaseModel):
        owner: str
        name: str

    context = {
        'devkits': [
            {'name': 'd1', 'ref': 'v0'},
            {'name': 'd2', 'ref': 'v1'},
        ],
        'simple': 'value',
        'nested': {'deep': {'value': 'original'}},
        'string_value': 'not_a_dict',  # This will trigger cannot-navigate when we try to navigate into it
        'direct_list': ['a', 'b', 'c'],
        'repo': Repo(owner='me', name='original'),
    }
    overrides = {
        'devkits.0.name': 'new-d1',
        'simple': 'new-value',
        'nested.deep.value': 'updated',
        'nonexistent.key': 'ignored',
        'devkits.2.name': 'out-of-range',
        'devkits.invalid.name': 'invalid-index',
        'string_value.key': 'cannot-navigate',  # Try to navigate into a string
        'direct_list.1': 'replaced',  # Direct list index replacement
        'repo.name': 'new_name',  # should not touch Repo instance
    }
    mock_logger = mocker.patch('repolish.loader.context.logger')
    apply_context_overrides(context, overrides)
    assert context['devkits'][0]['name'] == 'new-d1'
    assert context['simple'] == 'new-value'
    assert context['nested']['deep']['value'] == 'updated'
    assert context['direct_list'][1] == 'replaced'  # Direct list replacement works
    assert context['nonexistent']['key'] == 'ignored'

    # object fields are untouched; we logged a warning when traversal failed
    assert context['repo'].name == 'original'
    assert mock_logger.warning.call_count >= 4
    # one warning should be for navigating into our Repo object
    assert any(call.kwargs.get('current_type') == 'Repo' for call in mock_logger.warning.call_args_list)


def test_apply_context_overrides_nested_dict():
    """Test that nested dictionary structures are flattened to dot-notation."""
    context = {
        'my_provider': {
            'devkits': [
                {'name': 'd1', 'ref': 'v0'},
                {'name': 'd2', 'ref': 'v1'},
            ],
            'some_setting': 42,
            'nested': {'deep': {'value': 'original'}},
        },
        'other_provider': {
            'config': 'default',
        },
    }

    # Test nested dict structure
    overrides = {
        'my_provider': {
            'some_setting': 100,
            'devkits.0': {
                'name': 'new-d1',
                'ref': 'v2',
            },
            'nested.deep.value': 'updated',
        },
        'other_provider.config': 'overridden',  # Mix flat and nested
    }

    apply_context_overrides(context, overrides)

    # Check that nested overrides were applied
    assert context['my_provider']['some_setting'] == 100
    assert context['my_provider']['devkits'][0]['name'] == 'new-d1'
    assert context['my_provider']['devkits'][0]['ref'] == 'v2'
    assert context['my_provider']['nested']['deep']['value'] == 'updated'
    assert context['other_provider']['config'] == 'overridden'


def test_apply_override_edge_cases(mocker: MockerFixture):
    """Test edge cases in _apply_override function."""
    mock_logger = mocker.patch('repolish.loader.context.logger')

    # Test empty path_parts (should return early)
    context = {'test': 'value'}
    _apply_override(context, [], 'new-value')
    # Should not modify context and not log warnings
    assert context == {'test': 'value'}
    assert mock_logger.warning.call_count == 0


def test_apply_context_overrides_dotted_keys_in_nested_dict():
    """Test that dotted keys in nested dictionaries are properly flattened.

    Regression test for issue where 'base.codeguides': {'base.ref': 'value'}
    was not correctly flattened to 'base.codeguides.base.ref': 'value',
    resulting in 'base.ref' being treated as a literal key instead of a path.
    """
    context = {}  # Start with empty context - overrides create intermediate structures

    overrides = {
        'base.codeguides': {
            'base.ref': 'some-ref',
        },
    }

    apply_context_overrides(context, overrides)

    # Should create nested structure: base.codeguides.base.ref = 'some-ref'
    assert context['base']['codeguides']['base']['ref'] == 'some-ref'


def test_apply_overrides_to_model_helper(mocker: MockerFixture):
    """Helper should return a new model when overrides apply and warn on failure."""

    class M(BaseModel):
        a: int = 0

    instance = M()

    mock_logger = mocker.patch('repolish.loader.orchestrator.logger')

    # override valid field
    new = _apply_overrides_to_model(instance, {'a': 5}, provider='pid')
    assert isinstance(new, M)
    assert new.a == 5
    assert mock_logger.warning.call_count == 0

    # if the model transforms the value during validation but does not drop
    # the key we also should not warn (previous implementation would log
    # ignored_keys=[]). this simulates more complex Pydantic behaviour.
    class N(BaseModel):
        a: int = 0

        @field_validator('a', mode='after')
        def bump(cls, v: int) -> int:  # noqa: N805
            return v + 10

    ninst = N()
    mock_logger.reset_mock()
    nout = _apply_overrides_to_model(ninst, {'a': 1}, provider='pid')
    assert isinstance(nout, N)
    assert nout.a == 11  # validator applied
    assert mock_logger.warning.call_count == 0

    # override invalid field should log but still produce a model with
    # identical data (identity isn't guaranteed because we re-validated).
    mock_logger.reset_mock()
    out = _apply_overrides_to_model(instance, {'b': 1}, provider='pid')
    assert isinstance(out, M)
    assert out.a == instance.a
    assert mock_logger.warning.call_count == 1
    assert 'context_override_ignored' in str(
        mock_logger.warning.call_args[0][0],
    )

    # override with bad type triggers validation failure
    mock_logger.reset_mock()
    out2 = _apply_overrides_to_model(instance, {'a': 'nope'}, provider='pid')
    assert out2 is instance
    assert mock_logger.warning.call_count == 1
    assert 'context_override_validation_failed' in str(
        mock_logger.warning.call_args[0][0],
    )
