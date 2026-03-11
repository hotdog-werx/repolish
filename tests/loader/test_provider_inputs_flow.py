import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from repolish.loader import create_providers
from repolish.loader.models import (
    BaseContext,
    BaseInputs,
    Provider,
    ProviderEntry,
    get_provider_context,
    get_provider_inputs,
    get_provider_inputs_schema,
)
from tests.providers_inputs.shared import CtxA, InputA


def test_provider_input_schema_instantiation() -> None:
    """Helpers correctly locate the schema and instantiate a blank input."""

    class SomeInputs(BaseModel):
        foo: str = 'x'

    class SomeProvider(Provider[BaseContext, SomeInputs]):
        def create_context(self) -> BaseContext:
            return BaseContext()

        def get_inputs_schema(self) -> type[SomeInputs]:
            return SomeInputs

    provs: list[Provider[Any, Any]] = [SomeProvider()]

    assert get_provider_inputs_schema(SomeProvider, provs) is SomeInputs
    inst = get_provider_inputs(SomeProvider, provs)
    assert isinstance(inst, SomeInputs)
    assert inst.foo == 'x'

    # unknown provider class returns None
    class Other(Provider[BaseContext, BaseModel]):
        def create_context(self) -> BaseContext:
            return BaseContext()

    assert get_provider_inputs_schema(Other, provs) is None
    assert get_provider_inputs(Other, provs) is None

    # when multiple providers exist we can still lookup the one with inputs
    class A2(SomeProvider):
        pass

    provs.append(A2())
    assert get_provider_inputs_schema(A2, provs) is SomeInputs

    # continue assertions originally part of this test
    assert get_provider_inputs_schema(SomeProvider, provs) is SomeInputs
    inst = get_provider_inputs(SomeProvider, provs)
    assert isinstance(inst, SomeInputs)
    assert inst.foo == 'x'

    # unknown provider class returns None
    class Other(Provider[BaseContext, BaseModel]):
        def create_context(self) -> BaseContext:
            return BaseContext()

    assert get_provider_inputs_schema(Other, provs) is None
    assert get_provider_inputs(Other, provs) is None

    # when multiple providers exist we can still lookup the one with inputs
    class A2(SomeProvider):
        pass

    provs.append(A2())
    assert get_provider_inputs_schema(A2, provs) is SomeInputs


def test_get_provider_context_lookup() -> None:
    """Utility returns context matching name, alias or provider class."""

    class Ctx(BaseContext):
        value: int = 42

    class Prov1(Provider[Ctx, BaseModel]):
        def create_context(self) -> Ctx:
            return Ctx()

    class Prov2(Provider[BaseContext, BaseModel]):
        def create_context(self) -> BaseContext:
            return BaseContext()

    entries: list[ProviderEntry] = [
        ProviderEntry(
            provider_id='p1',
            alias='alias1',
            inst_type=Prov1,
            context=Ctx(),
        ),
        ProviderEntry(
            provider_id='p2',
            alias='alias2',
            inst_type=Prov2,
            context=BaseContext(),
        ),
    ]

    # lookup by class
    ctx = get_provider_context(Prov1, entries)
    assert isinstance(ctx, Ctx)

    # base provider returns None - all of them are subclasses
    assert get_provider_context(Provider, entries) is None

    # missing returns None
    assert get_provider_context(Prov1, [entries[1]]) is None


def test_provider_inputs_module_filtering() -> None:
    """Providers may inspect other providers' input schemas before emitting."""

    class Dummy(BaseContext):
        pass

    # the generic argument (InputA) only describes the type Btest expects to
    # receive; it does not constrain what the method returns. the loader will
    # match emitted values to recipients' schemas.
    class Btest(Provider[Dummy, InputA]):
        def create_context(self) -> Dummy:
            return Dummy()

        def get_inputs_schema(self) -> type[InputA]:
            return InputA

        def provide_inputs(
            self,
            own_context: Dummy,  # noqa: ARG002 - method signature must match base
            all_providers: list[ProviderEntry],
            provider_index: int,  # noqa: ARG002 - method signature must match base
        ) -> list[BaseInputs]:
            # inspect schemas rather than names; access via attributes for
            # clarity. previously callers unpacked a 3-tuple; the new
            # `ProviderEntry` class requires attribute access but the intent
            # is clearer.
            for entry in all_providers:
                if entry.input_type is InputA:
                    return [InputA(prob_a_input='x')]
            return []

    b_inst = Btest()
    # if A not in list, no inputs
    assert b_inst.provide_inputs(Dummy(), [], 0) == []

    # if A present, returns list
    assert b_inst.provide_inputs(
        Dummy(),
        [
            ProviderEntry(
                provider_id='a',
                alias='a',
                context={},
                input_type=InputA,
            ),
        ],
        0,
    ) == [
        InputA(prob_a_input='x'),
    ]


@dataclass
class TCase:
    name: str
    order: tuple[str, ...]
    expected: str


@pytest.mark.parametrize(
    'case',
    [
        TCase(
            name='b_first',
            order=('provider_b', 'provider_c', 'provider_a'),
            expected='provider_b',
        ),
        TCase(
            name='a_first',
            order=('provider_a', 'provider_c', 'provider_b'),
            expected='provider_c',
        ),
    ],
    ids=lambda c: c.name,
)
def test_provider_inputs_order(tmp_path: Path, case: TCase):
    """Integration: verify that providers receive inputs in load order.

    Provider A consumes the *first* value targeted at it during the
    `finalize_context` phase.  In previous versions inputs were only
    delivered to later providers, making behaviour order-dependent.  With
    the new distribution logic every provider sees all schema-matching
    payloads, so the result is now deterministic regardless of load order.

    The test is parametrized over two scenarios, and each scenario is
    described by a :class:`TCase` instance.  The `ids` callable uses the
    `name` field to generate readable test IDs.
    """
    base_set = Path(__file__).parent.parent / 'providers_inputs'

    # copy provider directories into tmp_path in the given order
    dirs: list[str] = []
    for name in case.order:
        src = base_set / name
        dest = tmp_path / name
        shutil.copytree(src, dest)
        dirs.append(str(dest))

    providers = create_providers([str(d) for d in dirs])

    # locate ProviderA's context and verify it's a typed model
    ctx_obj = None
    for c in providers.provider_contexts.values():
        if isinstance(c, CtxA):
            ctx_obj = c
            break
    assert ctx_obj is not None, 'ProviderA context not found or not a CtxA model'
    assert ctx_obj.prov_a_value == case.expected
