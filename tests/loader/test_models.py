import pytest
from pydantic import BaseModel

from repolish.loader.models import Provider


class _TContext(BaseModel):
    v: int = 1


class _TInputs(BaseModel):
    name: str = 'x'


def test_provider_is_abstract_and_requires_methods():
    # Cannot instantiate base Provider directly (abstract methods missing)
    with pytest.raises(TypeError):
        Provider()


def test_minimal_provider_defaults_and_behavior():
    class MinimalProvider(Provider[_TContext, _TInputs]):
        def get_provider_name(self) -> str:
            return 'minimal'

        def create_context(self) -> _TContext:
            return _TContext(v=42)

    p = MinimalProvider()
    ctx = p.create_context()
    assert isinstance(ctx, _TContext)
    assert ctx.v == 42

    # optional methods have sensible defaults
    assert p.collect_provider_inputs(ctx, [], 0) == {}
    assert p.finalize_context(ctx, [], [], 0) == ctx
    assert p.get_inputs_schema() is None


def test_provider_can_override_optional_methods():
    class OptProvider(Provider[_TContext, _TInputs]):
        def get_provider_name(self) -> str:
            return 'opt'

        def create_context(self) -> _TContext:
            return _TContext()

        def get_inputs_schema(self) -> type[_TInputs]:
            return _TInputs

    p = OptProvider()
    assert p.get_inputs_schema() is _TInputs
