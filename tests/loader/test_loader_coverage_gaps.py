from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from repolish import ProviderEntry
from repolish.config import RepolishConfig, ResolvedProviderInfo
from repolish.hydration.context import build_final_providers
from repolish.loader import (
    Accumulators,
    BaseContext,
    TemplateMapping,
    create_providers,
)
from repolish.loader import Provider as _ProviderBase
from repolish.loader.mappings import (
    _process_mapping_item,
    process_file_mappings,
)
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
    _store_new_context,
    _validate_raw_inputs,
    build_provider_metadata,
    finalize_provider_contexts,
    gather_received_inputs,
)
from repolish.loader.validation import _emit_provider_migration_suggestion
from repolish.misc import ctx_keys, ctx_to_dict


# shared message class used by generated provider modules
class SharedMsg(BaseModel):
    foo: str


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
    hit the early-return branch in `repolish/loader/mappings.py`; a
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
    """Using the public API, ensure `None` mapping entries are ignored.

    This test constructs a minimal provider that returns a mapping containing
    `None` alongside a normal string entry.  The accumulator should only
    contain the string entry once processed, exercising the `if v is None`
    branch of `_process_mapping_item`.
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
    fm = Minimal().create_file_mappings({})
    process_file_mappings('m', fm, acc2)
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
    fm_bad = inst.create_file_mappings({})
    process_file_mappings('bad', fm_bad, acc)
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
    assert adapter.provide_inputs({}, [], 0) == []

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
    _mig, _insts = build_provider_metadata(module_cache)


def test_ctx_to_dict_behaves_consistently():
    class M(BaseModel):
        x: int

    # BaseModel -> dict
    assert ctx_to_dict(M(x=1)) == {'x': 1}
    # dict passes through
    assert ctx_to_dict({'a': 2}) == {'a': 2}
    # None becomes empty dict
    assert ctx_to_dict(None) == {}
    # other types fallback to empty dict (safety)
    assert ctx_to_dict(123) == {}


def test_ctx_keys_helper():
    class M(BaseModel):
        x: int
        y: str = 'z'

    # BaseModel -> list of keys
    assert set(ctx_keys(M(x=5))) == {'x', 'y'}
    # dict behaves as dict keys
    assert ctx_keys({'foo': 1, 'bar': 2}) == ['foo', 'bar']
    # None and other types give empty list
    assert ctx_keys(None) == []
    assert ctx_keys(123) == []


def test_gather_received_inputs_variants() -> None:
    """Cover module path both with and without recipients after."""
    # provider1 has no recipients after (flag False)
    module_cache = [('p1', {})]
    instances = [None]
    provider_contexts: dict[str, object] = {}
    # new API now uses ProviderEntry rather than a raw tuple.  we can
    # construct a minimal entry; context is a plain dict and no schema is
    # declared.
    all_providers_list = [
        ProviderEntry(
            provider_id='p1',
            name=None,
            alias='p1',
            context={},
            input_type=None,
        ),
    ]
    has_recipient_after = [False]
    # calling gather_received_inputs directly
    got = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        has_recipient_after,
    )
    assert got == {}

    # now provider with recipient after and a collect function
    has_recipient_after = [True]

    def send(ctx: dict, allp: list, idx: int) -> list:
        return [{'foo': 1}]

    module_cache = [('p2', {'provide_inputs': send})]
    got = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
        has_recipient_after,
    )
    # unresolved recipient dropped, so result remains empty
    assert got == {}


def test_overrides_affect_inputs(
    tmp_path: Path,
    make_provider: Callable[[str, str], str],
):
    """Providers should see config overrides when computing inputs.

    This test exercises the full three-phase workflow and ensures that
    contexts passed into `provide_inputs` and `finalize_context` are
    always Pydantic models.  previous iterations accidentally allowed
    dictionaries to leak through which broke class-based providers once
    overrides were applied.
    """
    sender_src = """
from pydantic import BaseModel
from repolish.loader.models import Provider, ProviderEntry
from tests.loader.test_loader_coverage_gaps import SharedMsg as Msg


class Repo(BaseModel):
    owner: str
    name: str


class Ctx(BaseModel):
    foo: str
    repo: Repo


class Sender(Provider[Ctx, Msg]):
    def get_provider_name(self):
        return 'sender'

    def create_context(self):
        # include a nested model to exercise dot-notation overrides
        return Ctx(foo='original', repo=Repo(owner='me', name='init'))

    def get_inputs_schema(self):
        return Msg

    def provide_inputs(self, own_context, all_providers, provider_index):
        # when the override utility is corrected we will always receive a
        # real model here; assert to catch regressions.
        assert not isinstance(own_context, dict)
        return [Msg(foo=own_context.foo)]
"""
    recv_src = """
from pydantic import BaseModel
from repolish.loader.models import Provider, ProviderEntry
from tests.loader.test_loader_coverage_gaps import SharedMsg as Msg


class RecCtx(BaseModel):
    got: str | None = None


class Receiver(Provider[RecCtx, Msg]):
    def get_provider_name(self):
        return 'receiver'

    def create_context(self):
        return RecCtx()

    def get_inputs_schema(self):
        return Msg

    def finalize_context(self, own_context, received_inputs, all_providers, provider_index):
        assert not isinstance(own_context, dict)
        if received_inputs:
            own_context.got = received_inputs[0].foo
        return own_context
"""
    sdir = make_provider(sender_src, 'sender')
    rdir = make_provider(recv_src, 'receiver')
    # move the generated provider modules into a `templates` subdirectory so
    # they match the behaviour of a linked provider with non-empty
    # `templates_dir`.  `build_final_providers` will later resolve the
    # directories to `<target>/templates`.
    for d in (sdir, rdir):
        sub = Path(d) / 'templates'
        sub.mkdir(exist_ok=True)
        # move original repolish module into subdir
        orig = Path(d) / 'repolish.py'
        if orig.exists():
            orig.rename(sub / 'repolish.py')

    # the real application path goes through `build_final_providers`
    # which wraps `create_providers` and then merges any project-level
    # provider config/overrides.  using that helper gives us confidence that
    # `provide_inputs` will see the updated context (previously the test
    # exercised `create_providers` directly which hid a bug).
    # global `context_overrides` argument is deprecated and isn't where
    # provider code actually looks; overrides live on the per-provider
    # configuration (cf. `ResolvedProviderInfo.context_overrides`).  the
    # previous test variant accidentally passed them globally which hid a
    # bug in real-world invocations.
    # when Repolish resolves provider directories it appends
    # `templates_dir`; make our manually constructed config behave the
    # same way so the test mirrors real usage.
    sdir_sub = Path(sdir) / 'templates'
    rdir_sub = Path(rdir) / 'templates'

    cfg = RepolishConfig(
        config_dir=tmp_path,
        directories=[sdir_sub, rdir_sub],
        context={},
        anchors={},
        providers={
            'sender': ResolvedProviderInfo(
                alias='sender',
                target_dir=Path(sdir),
                templates_dir='templates',
                context=None,
                context_overrides={
                    'foo': 'overridden',
                    'repo.name': 'new_name',
                },
            ),
            'receiver': ResolvedProviderInfo(
                alias='receiver',
                target_dir=Path(rdir),
                templates_dir='templates',
            ),
        },
    )
    # add provider definitions with scoped overrides
    providers = build_final_providers(cfg)

    # receiver's context after finalization should include the 'got' key
    # with the value produced by Sender.provide_inputs, which proves that
    # Sender saw the override before emitting inputs.
    # fetch by explicit provider path rather than relying on dict order
    recv_pid = str(rdir_sub.as_posix())
    send_pid = str(sdir_sub.as_posix())

    receiver_ctx = providers.provider_contexts.get(recv_pid, {})
    # contexts may be BaseModel instances or plain dicts depending on merge
    if isinstance(receiver_ctx, BaseModel):
        rc = cast('Any', receiver_ctx)
        assert rc.got == 'overridden'
    else:
        rc2 = cast('dict', receiver_ctx)
        assert rc2.get('got') == 'overridden'

    sender_ctx = providers.provider_contexts.get(send_pid, {})
    if isinstance(sender_ctx, BaseModel):
        sc = cast('Any', sender_ctx)
        assert sc.repo.name == 'new_name'
    else:
        sc2 = cast('dict', sender_ctx)
        assert sc2.get('repo', {}).get('name') == 'new_name'


def test_invalid_override_preserves_model(
    make_provider: Callable[[str, str], str],
):
    """An override that fails validation should not convert the context to a dict.

    The loader logs a warning when an override cannot be applied so that
    callers know something went wrong (extra field, wrong type, etc.).
    """
    src = """
from pydantic import BaseModel
from repolish.loader.models import Provider


class IntCtx(BaseModel):
    x: int = 0


class P(Provider[IntCtx, BaseModel]):
    def get_provider_name(self):
        return 'p'

    def create_context(self):
        return IntCtx()
"""
    pdir = make_provider(src, 'p')
    # patch the orchestrator logger so we can observe warnings

    mock_logger = MagicMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            'repolish.loader.orchestrator.logger',
            mock_logger,
        )
        providers = create_providers(
            [pdir],
            context_overrides={'x': 'not-an-int'},
        )
        ctx = next(iter(providers.provider_contexts.values()))
        assert isinstance(ctx, BaseModel)
        # cast to Any so we can access the field without type errors

        ctx_typed = cast('Any', ctx)
        # original value should remain unchanged
        assert ctx_typed.x == 0

        # we should have logged at least one warning about the failed
        # override; use the message key as an indicator.
        assert mock_logger.warning.call_count >= 1
        assert any(
            'context_override_validation_failed' in str(call.args[0]) for call in mock_logger.warning.call_args_list
        )


def test_override_unknown_field_logs_warning(
    make_provider: Callable[[str, str], str],
):
    """Override targeting fields that don't exist should be ignored and reported via a warning."""
    src = """
from pydantic import BaseModel
from repolish.loader import Provider


class SimpleCtx(BaseModel):
    a: int = 1


class P(Provider[SimpleCtx, BaseModel]):
    def get_provider_name(self):
        return 'p'

    def create_context(self):
        return SimpleCtx()
"""
    pdir = make_provider(src, 'p')

    mock_logger = MagicMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            'repolish.loader.orchestrator.logger',
            mock_logger,
        )
        providers = create_providers([pdir], context_overrides={'y': 'value'})
        ctx = next(iter(providers.provider_contexts.values()))
        assert isinstance(ctx, BaseModel)
        ctx_typed = cast('Any', ctx)
        assert not hasattr(ctx_typed, 'y')
        assert mock_logger.warning.call_count >= 1
        # the override added a key that the model doesn't know about; the
        # validation step will silently drop that key, so we expect a warning
        # about ignored values rather than a validation error.
        assert any('context_override_ignored' in str(call.args[0]) for call in mock_logger.warning.call_args_list)


def test_override_on_nested_default_model(
    make_provider: Callable[[str, str], str],
):
    """Overrides may populate nested structures that exist only via defaults.

    The loader dumps the BaseModel to a dict, applies the override, then
    validates back into the model class.  If the model defines nested fields
    with default instances, the override can target sub-keys even when the
    dump initially contains only empty values.
    """
    src = """
from pydantic import BaseModel
from repolish.loader.models import Provider


class Inner(BaseModel):
    x: int = 0


class Ctx(BaseModel):
    inner: Inner = Inner()


class P(Provider[Ctx, BaseModel]):
    def get_provider_name(self):
        return 'p'

    def create_context(self):
        return Ctx()
"""
    pdir = make_provider(src, 'p')
    providers = create_providers([pdir], context_overrides={'inner.x': 42})
    ctx = next(iter(providers.provider_contexts.values()))
    assert isinstance(ctx, BaseModel)
    ctx_typed = cast('Any', ctx)
    assert hasattr(ctx_typed, 'inner')
    assert ctx_typed.inner.x == 42


def test_validate_raw_inputs_and_helpers() -> None:
    # inputs_schema Null returns unchanged list
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
    """Providers should always have `finalize_context` invoked.

    Previously we skipped providers when `received_inputs` was empty; this
    prevented context mutation for providers that don't emit inputs.  The
    current behaviour calls the hook unconditionally (aside from missing
    instances).  The test exercises both paths.
    """
    # skip when instance None (no provider to call)
    ctxs: dict[str, object] = {}
    finalize_provider_contexts([('p', {})], [None], {}, cast('dict', ctxs), [])
    assert ctxs == {}

    # provider with no inputs still has finalize_context executed
    class Setter(DummyProvider):
        def finalize_context(
            self,
            own_context: BaseContext,  # noqa: ARG002 - parameter may be unused
            received_inputs: list[BaseModel],  # noqa: ARG002 - parameter may be unused
            all_providers: list[ProviderEntry],  # noqa: ARG002 - parameter may be unused
            provider_index: int,  # noqa: ARG002 - parameter may be unused
        ) -> BaseContext:
            return cast('BaseContext', {'called': True})

    ctxs: dict[str, object] = {}
    inst = Setter()
    finalize_provider_contexts([('p', {})], [inst], {}, cast('dict', ctxs), [])
    assert ctxs == {'p': {'called': True}}


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
