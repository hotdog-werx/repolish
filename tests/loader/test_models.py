import datetime

import pytest
from pydantic import BaseModel

from repolish.loader.models import BaseContext, Provider


class _TContext(BaseContext):
    v: int = 1


class _TInputs(BaseModel):
    name: str = 'x'


def test_provider_is_abstract_and_requires_methods():
    # Cannot instantiate base Provider directly (abstract methods missing)
    with pytest.raises(TypeError):
        Provider()


def test_minimal_provider_defaults_and_behavior():
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


def test_basecontext_includes_repolish_field():
    from repolish.loader.models import BaseContext, GlobalContext  # noqa: PLC0415 - testing import

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
