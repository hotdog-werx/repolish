import datetime
from unittest import mock

import pytest
from pydantic import BaseModel

from repolish.providers import logger
from repolish.providers.models import (
    BaseContext,
    BaseInputs,
    Provider,
    ProviderInfo,
)
from repolish.providers.models.provider import _get_provider_generic_args


class _TContext(BaseContext):
    v: int = 1


class _TInputs(BaseModel):
    name: str = 'x'


def test_provider_is_abstract_and_requires_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    # The base Provider class is concrete; a bare instance returns a
    # generic BaseContext and logs a warning rather than failing.
    mock_warn = mock.MagicMock()
    monkeypatch.setattr(logger, 'warning', mock_warn)

    p = Provider[_TContext, _TInputs]()
    ctx = p.create_context()
    assert isinstance(ctx, BaseContext)

    # logger.warning should have been called with the event name as first arg
    assert mock_warn.call_count == 1
    assert 'provider_context_inference_failed' in str(mock_warn.call_args[0][0])


def test_minimal_provider_defaults_and_behavior():
    # when the subclass supplies a simple context model with defaults the
    # explicit override remains supported and behaves as before
    class MinimalProvider(Provider[_TContext, _TInputs]):
        def create_context(self) -> _TContext:
            return _TContext(v=42)

    p = MinimalProvider()
    ctx = p.create_context()
    assert isinstance(ctx, _TContext)
    assert ctx.v == 42

    # optional methods have sensible defaults
    assert p.provide_inputs(ctx, [], 0) == []

    assert p.finalize_context(ctx, [], [], 0) == ctx
    assert p.get_inputs_schema() is None


def test_provider_can_override_optional_methods():
    class OptProvider(Provider[_TContext, _TInputs]):
        def create_context(self) -> _TContext:
            return _TContext()

        def get_inputs_schema(self) -> type[_TInputs]:
            return _TInputs

    p = OptProvider()
    assert p.get_inputs_schema() is _TInputs


def test_inputs_schema_inference():
    """Schema is inferred from the generic argument when it's not BaseInputs."""

    class Custom(BaseInputs):
        foo: str = 'x'

    class Infer(Provider[_TContext, Custom]):
        pass

    inst = Infer()
    assert inst.get_inputs_schema() is Custom

    # generic BaseInputs should still return None
    class NoSchema(Provider[_TContext, BaseInputs]):
        pass

    assert NoSchema().get_inputs_schema() is None


def test_get_generic_args_helper():
    # returns both parameters when present
    class A(Provider[_TContext, _TInputs]):
        pass

    ctx_cls, inp_cls = _get_provider_generic_args(A)
    assert ctx_cls is _TContext
    assert inp_cls is _TInputs

    class B(Provider[_TContext, BaseInputs]):
        pass

    ctx2, inp2 = _get_provider_generic_args(B)
    assert ctx2 is _TContext
    assert inp2 is BaseInputs

    class C:
        pass

    assert _get_provider_generic_args(C) == (None, None)


def test_default_context_inference():
    """SessionBundle with a concrete context type get a default instance."""

    class Inferred(Provider[_TContext, _TInputs]):
        # no override of create_context; default implementation should kick in
        pass

    # note: _TContext already defaults to v=1
    p = Inferred()
    ctx = p.create_context()
    assert isinstance(ctx, _TContext)
    assert ctx.v == 1


def test_inference_failure_shows_hint(monkeypatch: pytest.MonkeyPatch):
    # when the inferred context class requires arguments the default
    # implementation will catch the error, emit a warning, and return a
    # bare BaseContext rather than raise.
    class NeedsArg(BaseContext):
        def __init__(self, foo: int) -> None:
            super().__init__()
            self.foo = foo

    class BadProvider(Provider[NeedsArg, _TInputs]):
        pass

    mock_warn = mock.MagicMock()
    monkeypatch.setattr(logger, 'warning', mock_warn)

    ctx = BadProvider().create_context()
    assert isinstance(ctx, BaseContext)
    assert mock_warn.call_count == 1
    assert 'provider_context_instantiation_failed' in str(
        mock_warn.call_args[0][0],
    )


@pytest.mark.parametrize(
    ('version', 'expected'),
    [
        ('1.2.3', 1),
        ('v2.0.0', 2),
        ('', None),
        ('not-a-version', None),  # non-numeric major → ValueError
        ('.', None),  # empty split result → ValueError
    ],
    ids=['numeric', 'v-prefix', 'empty', 'non-numeric', 'dot-only'],
)
def test_provider_info_major_version(
    version: str,
    expected: int | None,
) -> None:
    """major_version parses the integer major or returns None on bad input."""
    info = ProviderInfo(version=version)
    assert info.major_version == expected


def test_basecontext_includes_repolish_field():
    from repolish.providers.models import BaseContext, GlobalContext  # noqa: PLC0415 - testing import

    bc = BaseContext()
    assert hasattr(bc, 'repolish')
    assert isinstance(bc.repolish, GlobalContext)
    # default fields may be populated based on the git repository
    # where the tests run; we simply ensure the nested attributes exist and
    # that the legacy accessors mirror them.
    assert hasattr(bc.repolish.repo, 'owner')
    assert hasattr(bc.repolish.repo, 'name')
    # year should reflect the current calendar year; using datetime here
    # keeps the test stable regardless of when it's executed.
    assert bc.repolish.year == datetime.datetime.now(datetime.UTC).year


def test_get_global_context_falls_back_when_git_raises() -> None:
    # get_global_context is best-effort: if git.get_owner_repo raises, owner
    # and name should fall back to 'Unknown' rather than propagating.
    from repolish.providers.models import get_global_context  # noqa: PLC0415

    with mock.patch(
        'repolish.providers.models.context._get_owner_repo',
        side_effect=OSError('no git'),
    ):
        ctx = get_global_context()

    assert ctx.repo.owner == 'Unknown'
    assert ctx.repo.name == 'Unknown'


def test_provider_create_default_symlinks_returns_empty_list():
    """Base Provider.create_default_symlinks() returns [] by default."""
    provider = Provider()
    assert provider.create_default_symlinks() == []
