from pydantic import BaseModel, field_validator
from pytest_mock import MockerFixture

from repolish.loader.context import _apply_override, apply_context_overrides
from repolish.loader.models import BaseContext
from repolish.loader.orchestrator import _apply_overrides_to_model


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

    class M(BaseContext):
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
    class N(BaseContext):
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
