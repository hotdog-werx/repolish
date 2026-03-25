"""Tests for ModeHandler dispatch in Provider hooks.

Verifies that:
- Each of the four hooks dispatches to the registered mode handler.
- Handler instances are lazily created and cached.
- Hooks fall back to the no-op default when no handler is registered for the mode.
- Directly overriding a hook on the Provider subclass takes priority over any
  mode handler (backward-compat guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from repolish import (
    BaseContext,
    BaseInputs,
    FinalizeContextOptions,
    ModeHandler,
    ProvideInputsOptions,
    Provider,
    call_provider_method,
)
from repolish.providers.models.context import ProviderInfo, RepolishContext
from repolish.providers.models.files import TemplateMapping
from repolish.providers.models.workspace import (
    ProviderSession,
    WorkspaceContext,
)

# ---------------------------------------------------------------------------
# Helpers: build a BaseContext whose repolish.workspace.mode is set
# ---------------------------------------------------------------------------


def _make_ctx(mode: str) -> BaseContext:
    from typing import Literal, cast

    _mode = cast('Literal["root", "member", "standalone"]', mode)
    workspace = WorkspaceContext(mode=_mode, root_dir=Path('/tmp'))
    session = ProviderSession(mode=_mode)
    provider_info = ProviderInfo(session=session)
    rc = RepolishContext(workspace=workspace, provider=provider_info)
    return BaseContext(repolish=rc)


# ---------------------------------------------------------------------------
# Small context / inputs types used in tests
# ---------------------------------------------------------------------------


class MyCtx(BaseContext):
    value: str = ''


class MyInputs(BaseInputs):
    tag: str = ''


# ---------------------------------------------------------------------------
# Concrete ModeHandler subclasses
# ---------------------------------------------------------------------------


class RootHandler(ModeHandler[MyCtx, MyInputs]):
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[MyCtx],
    ) -> list[MyInputs]:
        return [MyInputs(tag='from-root')]

    def finalize_context(
        self,
        opt: FinalizeContextOptions[MyCtx, MyInputs],
    ) -> MyCtx:
        opt.own_context.value = 'finalized-by-root'
        return opt.own_context

    def create_file_mappings(self, context):
        return {'root.md': 'root.md'}

    def create_anchors(self, context):
        return {'ROOT': 'yes'}


class MemberHandler(ModeHandler[MyCtx, MyInputs]):
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[MyCtx],
    ) -> list[MyInputs]:
        return [MyInputs(tag='from-member')]

    def finalize_context(
        self,
        opt: FinalizeContextOptions[MyCtx, MyInputs],
    ) -> MyCtx:
        opt.own_context.value = 'finalized-by-member'
        return opt.own_context

    def create_file_mappings(self, context):
        return {'member.md': 'member.md'}

    def create_anchors(self, context):
        return {'MEMBER': 'yes'}


class HandlerWithProvideOverride(ModeHandler[MyCtx, MyInputs]):
    """Used to verify that direct Provider override bypasses the handler."""

    def provide_inputs(
        self,
        opt: ProvideInputsOptions[MyCtx],
    ) -> list[MyInputs]:
        return [MyInputs(tag='from-handler-should-not-run')]


# ---------------------------------------------------------------------------
# Provider fixture
# ---------------------------------------------------------------------------


class _HandledProvider(Provider[MyCtx, MyInputs]):
    root_mode = RootHandler
    member_mode = MemberHandler
    # standalone_mode intentionally unset


# ---------------------------------------------------------------------------
# Tests: provide_inputs dispatch
# ---------------------------------------------------------------------------


@dataclass
class ProvideInputsCase:
    name: str
    mode: str
    expected_tag: str


@pytest.mark.parametrize(
    'case',
    [
        ProvideInputsCase(
            name='root_mode_dispatches',
            mode='root',
            expected_tag='from-root',
        ),
        ProvideInputsCase(
            name='member_mode_dispatches',
            mode='member',
            expected_tag='from-member',
        ),
    ],
    ids=lambda c: c.name,
)
def test_provide_inputs_dispatches_to_handler(case: ProvideInputsCase) -> None:
    provider = _HandledProvider()
    ctx = _make_ctx(case.mode)
    ctx.__class__ = MyCtx  # keep mode info but use typed subclass
    # build a proper MyCtx keeping the repolish field from the base context
    typed_ctx = MyCtx(repolish=ctx.repolish)
    inputs = call_provider_method(
        provider,
        'provide_inputs',
        ProvideInputsOptions(own_context=typed_ctx, all_providers=[], provider_index=0),
    )
    assert isinstance(inputs, list)
    assert len(inputs) == 1
    item = inputs[0]
    assert isinstance(item, MyInputs)
    assert item.tag == case.expected_tag


def test_provide_inputs_no_handler_returns_empty() -> None:
    provider = _HandledProvider()
    ctx = MyCtx(repolish=_make_ctx('standalone').repolish)
    result = call_provider_method(
        provider,
        'provide_inputs',
        ProvideInputsOptions(own_context=ctx, all_providers=[], provider_index=0),
    )
    assert result == []


# ---------------------------------------------------------------------------
# Tests: finalize_context dispatch
# ---------------------------------------------------------------------------


@dataclass
class FinalizeCase:
    name: str
    mode: str
    expected_value: str


@pytest.mark.parametrize(
    'case',
    [
        FinalizeCase(
            name='root_mode_dispatches',
            mode='root',
            expected_value='finalized-by-root',
        ),
        FinalizeCase(
            name='member_mode_dispatches',
            mode='member',
            expected_value='finalized-by-member',
        ),
    ],
    ids=lambda c: c.name,
)
def test_finalize_context_dispatches_to_handler(case: FinalizeCase) -> None:
    provider = _HandledProvider()
    ctx = MyCtx(repolish=_make_ctx(case.mode).repolish)
    result = call_provider_method(
        provider,
        'finalize_context',
        FinalizeContextOptions(own_context=ctx, received_inputs=[], all_providers=[], provider_index=0),
    )
    assert isinstance(result, MyCtx)
    assert result.value == case.expected_value


def test_finalize_context_no_handler_returns_unchanged() -> None:
    provider = _HandledProvider()
    ctx = MyCtx(repolish=_make_ctx('standalone').repolish, value='original')
    result = call_provider_method(
        provider,
        'finalize_context',
        FinalizeContextOptions(own_context=ctx, received_inputs=[], all_providers=[], provider_index=0),
    )
    assert isinstance(result, MyCtx)
    assert result.value == 'original'


# ---------------------------------------------------------------------------
# Tests: create_file_mappings dispatch
# ---------------------------------------------------------------------------


@dataclass
class FileMappingsCase:
    name: str
    mode: str
    expected_key: str


@pytest.mark.parametrize(
    'case',
    [
        FileMappingsCase(
            name='root_mode_dispatches',
            mode='root',
            expected_key='root.md',
        ),
        FileMappingsCase(
            name='member_mode_dispatches',
            mode='member',
            expected_key='member.md',
        ),
    ],
    ids=lambda c: c.name,
)
def test_create_file_mappings_dispatches_to_handler(
    case: FileMappingsCase,
) -> None:
    provider = _HandledProvider()
    ctx = MyCtx(repolish=_make_ctx(case.mode).repolish)
    result = call_provider_method(provider, 'create_file_mappings', ctx)
    assert isinstance(result, dict)
    assert case.expected_key in result


def test_create_file_mappings_no_handler_returns_empty() -> None:
    provider = _HandledProvider()
    ctx = MyCtx(repolish=_make_ctx('standalone').repolish)
    assert call_provider_method(provider, 'create_file_mappings', ctx) == {}


# ---------------------------------------------------------------------------
# Tests: create_anchors dispatch
# ---------------------------------------------------------------------------


@dataclass
class AnchorsCase:
    name: str
    mode: str
    expected_key: str


@pytest.mark.parametrize(
    'case',
    [
        AnchorsCase(
            name='root_mode_dispatches',
            mode='root',
            expected_key='ROOT',
        ),
        AnchorsCase(
            name='member_mode_dispatches',
            mode='member',
            expected_key='MEMBER',
        ),
    ],
    ids=lambda c: c.name,
)
def test_create_anchors_dispatches_to_handler(case: AnchorsCase) -> None:
    provider = _HandledProvider()
    ctx = MyCtx(repolish=_make_ctx(case.mode).repolish)
    result = call_provider_method(provider, 'create_anchors', ctx)
    assert isinstance(result, dict)
    assert case.expected_key in result


def test_create_anchors_no_handler_returns_empty() -> None:
    provider = _HandledProvider()
    ctx = MyCtx(repolish=_make_ctx('standalone').repolish)
    assert call_provider_method(provider, 'create_anchors', ctx) == {}


# ---------------------------------------------------------------------------
# Tests: handler instance caching
# ---------------------------------------------------------------------------


def test_handler_instance_is_cached_across_calls() -> None:
    class _CountingHandler(ModeHandler[MyCtx, MyInputs]):
        _instances: int = 0

        def __init__(self) -> None:
            _CountingHandler._instances += 1

    class _CachingProvider(Provider[MyCtx, MyInputs]):
        root_mode = _CountingHandler

    _CountingHandler._instances = 0
    provider = _CachingProvider()
    ctx = MyCtx(repolish=_make_ctx('root').repolish)
    _opts = ProvideInputsOptions(own_context=ctx, all_providers=[], provider_index=0)
    call_provider_method(provider, 'provide_inputs', _opts)
    call_provider_method(provider, 'provide_inputs', _opts)
    assert _CountingHandler._instances == 1, 'handler should be instantiated only once'


def test_different_modes_get_different_handler_instances() -> None:
    provider = _HandledProvider()
    root_ctx = MyCtx(repolish=_make_ctx('root').repolish)
    member_ctx = MyCtx(repolish=_make_ctx('member').repolish)
    call_provider_method(provider, 'provide_inputs', ProvideInputsOptions(own_context=root_ctx, all_providers=[], provider_index=0))
    call_provider_method(provider, 'provide_inputs', ProvideInputsOptions(own_context=member_ctx, all_providers=[], provider_index=0))
    cache = vars(provider)['_mode_handler_instances']
    assert isinstance(cache['root'], RootHandler)
    assert isinstance(cache['member'], MemberHandler)
    assert cache['root'] is not cache['member']


# ---------------------------------------------------------------------------
# Tests: direct override on Provider subclass takes priority
# ---------------------------------------------------------------------------


def test_mode_handler_wins_over_direct_override() -> None:
    """When a mode handler is registered, it wins over a direct provider override."""

    class _BothProvider(Provider[MyCtx, MyInputs]):
        root_mode = HandlerWithProvideOverride

        def provide_inputs(
            self,
            opt: ProvideInputsOptions[MyCtx],
        ) -> list[MyInputs]:
            return [MyInputs(tag='from-direct-override')]

    provider = _BothProvider()
    ctx = MyCtx(repolish=_make_ctx('root').repolish)
    inputs = call_provider_method(
        provider,
        'provide_inputs',
        ProvideInputsOptions(own_context=ctx, all_providers=[], provider_index=0),
    )
    assert isinstance(inputs, list)
    assert len(inputs) == 1
    item = inputs[0]
    assert isinstance(item, MyInputs)
    assert item.tag == 'from-handler-should-not-run'


def test_direct_override_runs_when_no_mode_handler() -> None:
    """When no mode handler is registered, the provider's own override is called."""

    class _DirectProvider(Provider[MyCtx, MyInputs]):
        def provide_inputs(
            self,
            opt: ProvideInputsOptions[MyCtx],
        ) -> list[MyInputs]:
            return [MyInputs(tag='from-direct-override')]

    provider = _DirectProvider()
    ctx = MyCtx(repolish=_make_ctx('root').repolish)
    inputs = call_provider_method(
        provider,
        'provide_inputs',
        ProvideInputsOptions(own_context=ctx, all_providers=[], provider_index=0),
    )
    assert isinstance(inputs, list)
    assert len(inputs) == 1
    item = inputs[0]
    assert isinstance(item, MyInputs)
    assert item.tag == 'from-direct-override'


# ---------------------------------------------------------------------------
# Tests: ModeHandler base class no-op defaults
# ---------------------------------------------------------------------------


def test_mode_handler_base_defaults() -> None:
    """ModeHandler base class methods should all return empty / unchanged values."""
    handler: ModeHandler[MyCtx, MyInputs] = ModeHandler()
    ctx = MyCtx(repolish=_make_ctx('root').repolish)
    assert (
        handler.provide_inputs(
            ProvideInputsOptions(
                own_context=ctx,
                all_providers=[],
                provider_index=0,
            ),
        )
        == []
    )
    assert (
        handler.finalize_context(
            FinalizeContextOptions(
                own_context=ctx,
                received_inputs=[],
                all_providers=[],
                provider_index=0,
            ),
        )
        is ctx
    )
    assert handler.create_file_mappings(ctx) == {}
    assert handler.create_anchors(ctx) == {}


# ---------------------------------------------------------------------------
# Tests: ModeHandler receives provider attributes from call_provider_method
# ---------------------------------------------------------------------------


def test_mode_handler_receives_provider_attributes() -> None:
    """Handler instantiated via call_provider_method gets provider attrs injected."""
    from pathlib import Path

    captured: dict[str, object] = {}

    class _CapturingHandler(ModeHandler[MyCtx, MyInputs]):
        def create_file_mappings(
            self,
            context: MyCtx,
        ) -> dict[str, str | TemplateMapping | None]:
            captured['templates_root'] = self.templates_root
            captured['alias'] = self.alias
            captured['version'] = self.version
            captured['package_name'] = self.package_name
            captured['project_name'] = self.project_name
            return {}

    class _AttrProvider(Provider[MyCtx, MyInputs]):
        root_mode = _CapturingHandler

    provider = _AttrProvider()
    provider.templates_root = Path('/some/provider/root')
    provider.alias = 'my-provider'
    provider.version = '1.2.3'
    provider.package_name = 'my_pkg'
    provider.project_name = 'my-pkg'

    ctx = MyCtx(repolish=_make_ctx('root').repolish)
    call_provider_method(provider, 'create_file_mappings', ctx)

    assert captured['templates_root'] == Path('/some/provider/root') / 'root'
    assert captured['alias'] == 'my-provider'
    assert captured['version'] == '1.2.3'
    assert captured['package_name'] == 'my_pkg'
    assert captured['project_name'] == 'my-pkg'
