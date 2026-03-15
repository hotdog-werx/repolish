from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest import mock
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from repolish import ProviderEntry
from repolish.config import RepolishConfig, ResolvedProviderInfo
from repolish.hydration.context import build_final_providers
from repolish.loader import (
    BaseContext,
    create_providers,
    logger,
)
from repolish.loader import Provider as _ProviderBase
from repolish.loader.context import _apply_overrides_to_model
from repolish.loader.exchange import (
    _collect_provider_contributions,
    _process_provider_fm,
    finalize_provider_contexts,
    gather_received_inputs,
)
from repolish.loader.models import Accumulators, GlobalContext
from repolish.loader.pipeline import (
    _build_all_providers_list,
    _synthesize_provider_context_for_pid,
)
from repolish.misc import ctx_keys, ctx_to_dict


# shared message class used by generated provider modules
class SharedMsg(BaseModel):
    foo: str


# ---- helpers and minimal provider implementations ------------------------
class DummyProvider(_ProviderBase):
    """Simplest concrete provider used in helpers."""

    def __init__(self, name: str = 'dummy') -> None:
        self._name = name

    def create_context(self) -> BaseModel | dict:
        return {}


def test_process_file_mappings_skips_none_values() -> None:
    """Ensure `None` mapping entries are silently skipped."""
    acc2 = Accumulators()
    _process_provider_fm('m', {'a.txt': None, 'b.txt': 'tmpl'}, acc2)
    assert acc2.merged_file_mappings == {'b.txt': 'tmpl'}


# ---- orchestrator helpers --------------------------------------------------


def test_process_provider_fm_skips_none_values() -> None:
    """Ensure `None` mapping entries are silently skipped by `_process_provider_fm`."""
    acc = Accumulators()
    _process_provider_fm('m', {'a.txt': None, 'b.txt': 'tmpl'}, acc)
    assert acc.merged_file_mappings == {'b.txt': 'tmpl'}


def test_process_provider_fm_none_populates_suppressed_sources() -> None:
    """A None-valued mapping entry is added to suppressed_sources, not file_mappings."""
    acc = Accumulators()
    _process_provider_fm(
        'm',
        {'.github/workflows/_ci-checks.yaml': None, 'other.txt': 'tmpl'},
        acc,
    )
    assert '.github/workflows/_ci-checks.yaml' in acc.suppressed_sources
    assert '.github/workflows/_ci-checks.yaml' not in acc.merged_file_mappings
    assert acc.merged_file_mappings == {'other.txt': 'tmpl'}


def test_collect_provider_contributions_skips_missing_instance():
    acc = Accumulators()
    # module_cache entry with no instance
    _collect_provider_contributions([('p', {})], {}, acc)
    # nothing should have changed
    assert acc.merged_anchors == {}
    assert acc.merged_file_mappings == {}


def test_apply_overrides_to_model_noop_returns_original() -> None:
    """When overrides don't change any value the original instance is returned."""

    class Ctx(BaseContext):
        x: int = 5

    ctx = Ctx()
    result = _apply_overrides_to_model(ctx, {'x': 5})
    assert result is ctx


def test_synthesize_provider_context_skips_already_populated() -> None:
    """When `provider_contexts[pid]` already holds a `BaseContext` the function exits early."""

    class Sentinel(DummyProvider):
        def create_context(self) -> BaseContext:
            msg = 'create_context must not be called'
            raise AssertionError(msg)

    existing = BaseContext()
    provider_contexts: dict[str, BaseContext] = {'p': existing}
    _synthesize_provider_context_for_pid(
        Sentinel(),
        'p',
        provider_contexts,
        GlobalContext(),
    )
    assert provider_contexts['p'] is existing


def test_build_all_providers_list_swallows_broken_schema(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exception branches for `get_inputs_schema` and `create_context` are swallowed.

    A provider that raises in any of those methods must not abort the build:
    * `get_inputs_schema` raising -> `input_type=None`
    * `create_context` raising  -> provider_contexts is left unchanged
    """

    class BrokenProvider(DummyProvider):
        def get_inputs_schema(self) -> type[BaseModel]:
            msg = 'broken get_inputs_schema'
            raise RuntimeError(msg)

        def create_context(self) -> BaseContext:
            msg = 'broken create_context'
            raise RuntimeError(msg)

    inst = BrokenProvider()
    module_cache = [('bp', {})]
    instances: list[_ProviderBase | None] = [inst]
    provider_contexts: dict[str, BaseContext] = {}
    result = _build_all_providers_list(
        module_cache,
        instances,
        provider_contexts,
    )
    assert len(result) == 1
    entry = result[0]
    assert entry.input_type is None
    assert entry.provider_id == 'bp'

    # create_context raising must not add an entry to provider_contexts
    mock_warn = mock.MagicMock()
    monkeypatch.setattr(logger, 'warning', mock_warn)

    _synthesize_provider_context_for_pid(
        inst,
        'bp',
        provider_contexts,
        GlobalContext(),
    )
    assert mock_warn.call_count == 1
    assert 'provider_create_context_raised' in str(mock_warn.call_args[0][0])
    assert 'bp' not in provider_contexts


# ---- exchange helpers ------------------------------------------------------


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
    # annotate so the type checker knows we intend the broader provider union
    instances: list[_ProviderBase | None] = [None]
    provider_contexts: dict[str, BaseContext] = {}
    # new API now uses ProviderEntry rather than a raw tuple.  we can
    # construct a minimal entry; context is a plain dict and no schema is
    # declared.
    all_providers_list = [
        ProviderEntry(
            provider_id='p1',
            alias='p1',
            context={},
            input_type=None,
        ),
    ]
    # calling gather_received_inputs directly
    got = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
    )
    assert got == {}

    # now provider with recipient after and a collect function

    def send(ctx: dict, allp: list, idx: int) -> list:
        return [{'foo': 1}]

    module_cache = [('p2', {'provide_inputs': send})]
    got = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers_list,
    )
    # unresolved recipient dropped, so result remains empty
    assert got == {}


def test_overrides_affect_inputs(
    tmp_path: Path,
    make_provider: Callable[[str, str], str],
):
    """Providers should see config overrides when computing inputs.

    This test exercises the full provider exchange workflow and ensures that
    contexts passed into `provide_inputs` and `finalize_context` are
    always Pydantic models.  previous iterations accidentally allowed
    dictionaries to leak through which broke class-based providers once
    overrides were applied.
    """
    sender_src = """
from repolish import Provider, ProviderEntry, BaseContext, BaseInputs
from tests.loader.test_loader_coverage_gaps import SharedMsg as Msg


class Repo(BaseContext):
    owner: str
    name: str


class Ctx(BaseContext):
    foo: str
    repo: Repo


class Sender(Provider[Ctx, Msg]):
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
from repolish import Provider, ProviderEntry, BaseContext, BaseInputs
from tests.loader.test_loader_coverage_gaps import SharedMsg as Msg


class RecCtx(BaseContext):
    got: str | None = None


class Receiver(Provider[RecCtx, Msg]):
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
    # The providers are created directly in their root directories; earlier
    # tests simulated the now-removed `templates_dir` behaviour by nesting
    # files under a `templates` subfolder.  That indirection is no longer
    # necessary.

    # the real application path goes through `build_final_providers`
    # which wraps `create_providers` and then merges any project-level
    # provider config/overrides.  using that helper gives us confidence that
    # `provide_inputs` will see the updated context (previously the test
    # exercised `create_providers` directly which hid a bug).
    # project configuration no longer supports a global context or
    # dotted overrides; all such values must be provided on the
    # per-provider entries (see <docs> for details).  our manual config
    # should therefore omit those keys entirely.  final provider
    # directories are exactly the paths returned by the loader; no extra
    # subdir is appended or expected.
    cfg = RepolishConfig(
        config_dir=tmp_path,
        providers={
            'sender': ResolvedProviderInfo(
                alias='sender',
                provider_root=Path(sdir),
                resources_dir=Path(sdir),
                context=None,
                context_overrides={
                    'foo': 'overridden',
                    'repo.name': 'new_name',
                },
            ),
            'receiver': ResolvedProviderInfo(
                alias='receiver',
                provider_root=Path(rdir),
                resources_dir=Path(rdir),
            ),
        },
    )
    # add provider definitions with scoped overrides
    providers = build_final_providers(cfg)

    # receiver's context after finalization should include the 'got' key
    # with the value produced by Sender.provide_inputs, which proves that
    # Sender saw the override before emitting inputs.
    # fetch by explicit provider path rather than relying on dict order
    recv_pid = str(Path(rdir).as_posix())
    send_pid = str(Path(sdir).as_posix())

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
from repolish.loader.models import Provider, BaseContext, BaseInputs


class IntCtx(BaseContext):
    x: int = 0


class P(Provider[IntCtx, BaseInputs]):
    def create_context(self):
        return IntCtx()
"""
    pdir = make_provider(src, 'p')
    # patch the orchestrator logger so we can observe warnings

    mock_logger = MagicMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            'repolish.loader.context.logger',
            mock_logger,
        )
        providers = create_providers(
            [pdir],
            context_overrides={'x': 'not-an-int'},
        )
        ctx = next(iter(providers.provider_contexts.values()))
        assert isinstance(ctx, BaseContext)
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
from repolish import Provider, BaseContext, BaseInputs


class SimpleCtx(BaseContext):
    a: int = 1


class P(Provider[SimpleCtx, BaseInputs]):
    def create_context(self):
        return SimpleCtx()
"""
    pdir = make_provider(src, 'p')

    mock_logger = MagicMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            'repolish.loader.context.logger',
            mock_logger,
        )
        providers = create_providers([pdir], context_overrides={'y': 'value'})
        ctx = next(iter(providers.provider_contexts.values()))
        assert isinstance(ctx, BaseContext)
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
from repolish import Provider, BaseContext, BaseInputs


class Inner(BaseContext):
    x: int = 0


class Ctx(BaseContext):
    inner: Inner = Inner()


class P(Provider[Ctx, BaseInputs]):
    def create_context(self):
        return Ctx()
"""
    pdir = make_provider(src, 'p')
    providers = create_providers([pdir], context_overrides={'inner.x': 42})
    ctx = next(iter(providers.provider_contexts.values()))
    assert isinstance(ctx, BaseContext)
    ctx_typed = cast('Any', ctx)
    assert hasattr(ctx_typed, 'inner')
    assert ctx_typed.inner.x == 42


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
