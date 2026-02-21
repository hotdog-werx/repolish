from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from repolish.loader import create_providers
from repolish.loader.mappings import (
    _process_mapping_item,
    process_file_mappings,
)
from repolish.loader.models import Provider as _ProviderBase
from repolish.loader.module_loader import (
    ModuleProviderAdapter,
    # helpers called indirectly in tests
    _collect_context_from_module,
    _handle_callable_create_ctx,
    collect_contexts_with_provider_map,
    inject_provider_instance_for_module,
)
from repolish.loader.orchestrator import (
    _create_context_wrapper_for,
    _process_phase_two,
)
from repolish.loader.three_phase import (
    _get_own_model,
    _normalize_inputs,
    _process_inputs_map,
    _retrieve_module_inputs,
    _store_new_context,
    _validate_raw_inputs,
    build_provider_metadata,
    finalize_provider_contexts,
    gather_received_inputs,
)
from repolish.loader.types import (
    Accumulators,
    TemplateMapping,
)
from repolish.loader.validation import _emit_provider_migration_suggestion


# ---- helpers and minimal provider implementations ------------------------
class DummyProvider(_ProviderBase):
    """Simplest concrete provider used in helpers."""

    def __init__(self, name: str = 'dummy') -> None:
        self._name = name

    def get_provider_name(self) -> str:
        return self._name

    def create_context(self) -> BaseModel | dict:
        return {}


# ---------------------------------------------------------------------------


def test_process_file_mappings_non_dict_feedback(
    make_provider: Callable[[str, str], str],
):
    """If module-style provider returns None the adapter still produces a dict.

    This test primarily exercises the adapter path and the helper that
    ignores non-`TemplateMapping` values (the integer case).  It does *not*
    hit the early-return branch in ``repolish/loader/mappings.py``; a
    separate test below covers that.
    """
    src = """
    def create_file_mappings(context):
        return None
    """
    # `make_provider` signature accepts a name, but the fixture is untyped
    # at call sites; silence the checker instead of changing every use.
    p = make_provider(src)  # type: ignore[call-arg]
    providers = create_providers([p])
    assert providers.file_mappings == {}

    # the integer value case exercises `_process_mapping_item` fallthrough
    acc = Accumulators(
        merged_anchors={},
        merged_file_mappings={},
        create_only_set=set(),
        delete_set=set(),
        history={},
    )
    _process_mapping_item('foo', 42, 'pid', acc)
    assert acc.merged_file_mappings == {}


def test_process_file_mappings_skips_none_values() -> None:
    """Using the public API, ensure ``None`` mapping entries are ignored.

    This test constructs a minimal provider that returns a mapping containing
    ``None`` alongside a normal string entry.  The accumulator should only
    contain the string entry once processed, exercising the ``if v is None``
    branch of ``_process_mapping_item``.
    """

    class Minimal(_ProviderBase):
        def get_provider_name(self) -> str:
            return 'm'

        def create_context(self) -> dict:
            return {}

        def create_file_mappings(
            self,
            context: object,  # noqa: ARG002 - parameter may be unused
        ) -> dict[str, str | TemplateMapping]:
            # include a None value which should be skipped
            return {  # type: ignore[return-value] - deliberately violates return type for test
                'a.txt': None,  # pyright: ignore[reportReturnType]
                'b.txt': 'tmpl',
            }

    acc2 = Accumulators(
        merged_anchors={},
        merged_file_mappings={},
        create_only_set=set(),
        delete_set=set(),
        history={},
    )
    process_file_mappings('m', Minimal(), {}, acc2)
    assert acc2.merged_file_mappings == {'b.txt': 'tmpl'}


# this test exercises a defensive branch that only exists for module-style
# providers via the adapter. after v1 we plan to drop the adapter and the
# guard can go away; at that point this test should be removed too.
# marking no-cover so that any future refactor of the guard doesn't force
# changes to unrelated coverage expectations.


def test_process_file_mappings_early_return_for_class_provider() -> None:  # pragma: no cover
    """A class-based provider returning a non-dict should bail out immediately."""

    class Bad(_ProviderBase):
        def get_provider_name(self) -> str:
            return 'bad'

        def create_context(self) -> dict:
            return {}

        # this return deliberately violates the declared return type;
        # clients should never do this. the branch path exercised below is
        # defensive and once our codebase is fully typed the only way to hit it
        # is by ignoring types. the `override` ignore has since become
        # unnecessary (the signature matches), but we still keep the
        # `return-value` ignore. revisit this entire test once the v1 adapter
        # support is removed, since the defensive branch can be deleted
        # entirely at that point.
        def create_file_mappings(
            self,
            context: dict[str, object],  # noqa: ARG002 - needs signature
        ) -> dict[str, str | TemplateMapping]:
            return 'not a dict'  # type: ignore[return-value]

    inst = Bad()

    acc = Accumulators(
        merged_anchors={},
        merged_file_mappings={},
        create_only_set=set(),
        delete_set=set(),
        history={},
    )
    process_file_mappings('bad', inst, {}, acc)
    assert acc.merged_file_mappings == {}


# ----- module_loader helpers ------------------------------------------------


def test_collect_context_from_module_with_context_var():
    """_collect_context_from_module should update merged dict with context var."""
    # build a fake module cache with context key
    module_dict = {'context': {'x': 1}}
    merged = {}
    # call function from loader.module_loader

    _collect_context_from_module(module_dict, merged)
    assert merged == {'x': 1}


def test_handle_callable_create_ctx_deprecated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When factory returns None a DeprecationWarning is emitted."""

    def factory(ctx: dict | None) -> None:
        return None

    merged = {}
    provider_map: dict[str, object] = {}
    with pytest.warns(DeprecationWarning, match='deprecated'):
        _handle_callable_create_ctx('p', factory, merged, provider_map)
    assert merged == {}
    assert provider_map == {'p': {}}


def test_collect_contexts_with_provider_map_variants(tmp_path: Path):
    """Exercise branches where context var exists and where none present."""
    # module with context variable
    m1 = {'context': {'a': 1}}
    # module with neither factory nor context
    m2 = {}
    merged, provider_map = collect_contexts_with_provider_map(
        [('p1', m1), ('p2', m2)],
    )
    assert merged['a'] == 1
    assert provider_map == {'p1': {'a': 1}, 'p2': {}}


def test_module_provider_adapter_basic_behavior():
    """Validate default returns and adapter helpers used in coverage gaps."""
    module_dict: dict[str, object] = {}
    adapter = ModuleProviderAdapter(module_dict, 'pid')

    # no original callables: methods should exercise fallbacks
    assert adapter.collect_provider_inputs({}, [], 0) == {}
    ctx = {'foo': 'bar'}
    assert adapter.finalize_context(ctx, [], [], 0) is ctx
    assert adapter.get_inputs_schema() is None

    # test wrapper injection prevention
    inject_provider_instance_for_module(module_dict, 'pid')
    # second call should be no-op (line 481)
    inject_provider_instance_for_module(module_dict, 'pid')

    # wrapper for create_context should convert BaseModel to dict
    class Ctx(BaseModel):
        x: int

    class P(_ProviderBase):
        def get_provider_name(self) -> str:
            return 'x'

        def create_context(self) -> BaseModel:
            return Ctx(x=5)

    inst = P()
    module_dict2: dict[str, object] = {}
    inject_provider_instance_for_module(module_dict2, 'p2')
    # replace wrapper with one generated from inst manually
    wrapper = _create_context_wrapper_for(inst)
    res = wrapper(None)
    assert res == {'x': 5}


def test_module_adapter_merge_create_only_and_delete():
    """Verify _add_create_only_entries and _add_delete_entries branches."""
    adapter = ModuleProviderAdapter({}, 'pid')
    merged: dict[str, str | TemplateMapping] = {}

    # create-only with a falsy item and a real item
    adapter._add_create_only_entries(merged, [None, 'foo.txt'])
    assert 'foo.txt' in merged

    # duplicate entry should be skipped
    adapter._add_create_only_entries(merged, ['foo.txt'])
    assert len(merged) == 1

    # delete entries: skip None, raise for bad type, skip existing key
    with pytest.raises(TypeError):
        adapter._add_delete_entries({}, [123])
    merged2: dict[str, str | TemplateMapping] = {'keep.txt': 'x'}
    adapter._add_delete_entries(merged2, [None, 'keep.txt', 'del.txt'])
    assert 'del.txt' in merged2


# ---- orchestrator helpers --------------------------------------------------


def test_create_context_wrapper_for_returns_plain_dict():
    inst = DummyProvider()
    wrapper = _create_context_wrapper_for(inst)
    assert wrapper(None) == {}


def test_process_phase_two_skips_missing_instance():
    acc = Accumulators(
        merged_anchors={},
        merged_file_mappings={},
        create_only_set=set(),
        delete_set=set(),
        history={},
    )
    # module_cache entry with no instance
    _process_phase_two([('p', {})], {}, {}, acc)
    # nothing should have changed
    assert acc.merged_anchors == {}
    assert acc.merged_file_mappings == {}


# ---- three_phase helpers ---------------------------------------------------


def test_build_provider_metadata_handles_bad_name():
    class BadName(_ProviderBase):
        def get_provider_name(self) -> str:
            msg = 'boom'
            raise RuntimeError(msg)

        def create_context(self) -> dict:
            return {}

    module_cache = [('p', {'_repolish_provider_instance': BadName()})]
    _mig, _insts, canon = build_provider_metadata(module_cache)
    assert canon == {}


def test_normalize_inputs_various():
    # raw None
    assert _normalize_inputs('p', None) is None
    # raw non-dict triggers warning and returns None
    assert _normalize_inputs('p', 'hello') is None


@pytest.mark.parametrize(
    ('module_dict', 'expect'),
    [
        ({}, None),
        ({'collect_provider_inputs': lambda _c, _a, _i: {'x': 1}}, {'x': 1}),
    ],
)
def test_retrieve_module_inputs_behaviors(
    module_dict: dict,
    expect: dict | None,
) -> None:
    if expect is None:
        assert _retrieve_module_inputs('p', 0, module_dict, {}, []) is None
    else:
        assert _retrieve_module_inputs('p', 0, module_dict, {}, []) == expect


def test_retrieve_module_inputs_raises() -> None:
    def bad(ctx: dict, allp: list, idx: int) -> None:
        raise RuntimeError

    with pytest.raises(RuntimeError):
        _retrieve_module_inputs(
            'p',
            0,
            {'collect_provider_inputs': bad},
            {},
            [],
        )


def test_process_inputs_map_unresolved():
    received: dict[str, list[object]] = {}
    _process_inputs_map('p', {'unknown': 1}, received, {}, {})
    assert received == {}


def test_gather_received_inputs_variants() -> None:
    """Cover module path both with and without recipients after."""
    # provider1 has no recipients after (flag False)
    module_cache = [('p1', {})]
    instances = [None]
    provider_contexts: dict[str, object] = {}
    all_providers_list = [('p1', {})]
    canonical: dict[str, str] = {}
    has_recipient_after = [False]
    # calling gather_received_inputs directly
    got = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        canonical,
        has_recipient_after,
    )
    assert got == {}

    # now provider with recipient after and a collect function
    has_recipient_after = [True]

    def send(ctx: dict, allp: list, idx: int) -> dict:
        return {'pX': {'foo': 1}}

    module_cache = [('p2', {'collect_provider_inputs': send})]
    got = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        canonical,
        has_recipient_after,
    )
    # unresolved recipient dropped, so result remains empty
    assert got == {}


def test_validate_raw_inputs_and_helpers() -> None:
    # inputs_schema None returns unchanged list
    assert _validate_raw_inputs([1, 2, 3], None) == [1, 2, 3]

    class S(BaseModel):
        a: int

    # valid inputs should round-trip
    validated = _validate_raw_inputs([S(a=1), {'a': 2}], S)
    assert isinstance(validated[0], S)
    assert isinstance(validated[1], S)

    # _get_own_model error fallback
    class E(_ProviderBase):
        def get_provider_name(self) -> str:
            return 'e'

        def create_context(self) -> dict:
            raise RuntimeError

    assert _get_own_model(E(), {'p': {'foo': 'bar'}}, 'p') == {'foo': 'bar'}

    # _store_new_context accepts dict and raises on bad type
    store_ctx: dict[str, dict[str, object]] = {}
    _store_new_context(cast('dict[str, object]', store_ctx), 'p', {'x': 1})
    assert cast('dict', store_ctx)['p']['x'] == 1

    with pytest.raises(TypeError):
        _store_new_context({}, 'p', 123)


def test_finalize_provider_contexts_edge_cases() -> None:
    """Calling finalize_provider_contexts on no-op inputs should be a no-op.

    Exercises the early-`continue` paths for missing instance and for empty
    ``raw_inputs``. These guards are important because the loop in the
    production code iterates every provider and silently skipping them is the
    desired behaviour; the test therefore asserts the accumulator remains
    empty after the call so refactors can't accidentally start populating it.
    """
    # skip when instance None
    ctxs: dict[str, object] = {}
    finalize_provider_contexts([('p', {})], [None], {}, cast('dict', ctxs), [])
    assert ctxs == {}

    # skip when no raw inputs (provider exists but received none)
    ctxs: dict[str, object] = {}
    inst = DummyProvider()
    finalize_provider_contexts([('p', {})], [inst], {}, cast('dict', ctxs), [])
    assert ctxs == {}


def test_emit_provider_migration_suggestion_no_legacy():
    # should quietly return without warning
    _emit_provider_migration_suggestion({})


def test_emit_provider_migration_suggestion_includes_provider(
    mocker: MockerFixture,
) -> None:
    """When a provider_id is passed the log record should include it."""
    mock_logger = mocker.patch('repolish.loader.validation.logger')
    module = {'create_context': dict, 'file_mappings': {}}
    _emit_provider_migration_suggestion(module, provider_id='foo/bar')
    calls = [call for call in mock_logger.warning.call_args_list if 'provider_migration_suggestion' in str(call)]
    assert calls, 'expected a migration suggestion warning'
    assert any(call.kwargs.get('provider') == 'foo/bar' for call in calls)
