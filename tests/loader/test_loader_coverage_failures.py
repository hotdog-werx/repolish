from pathlib import Path

import pydantic_core
import pytest
from pydantic import BaseModel

from repolish.hydration.rendering import _load_and_validate_template
from repolish.loader.exchange import (
    _retrieve_instance_inputs,
    _schema_matches,
    _validate_raw_inputs,
    finalize_provider_contexts,
)
from repolish.loader.models import (
    BaseContext,
    BaseInputs,
    ProviderEntry,
    Providers,
    TemplateMapping,
)
from repolish.loader.models import (
    Provider as _ProviderBase,
)


class BadInst(_ProviderBase[BaseContext, BaseModel]):
    def create_context(self) -> BaseContext:
        raise ValueError

    # implement the *new* hook; the old alias is provided by the base
    # class and will warn if invoked.
    def provide_inputs(
        self,
        own_context: BaseContext,  # noqa: ARG002 - method signature must match base
        all_providers: list[ProviderEntry],  # noqa: ARG002 - method signature must match base
        provider_index: int,  # noqa: ARG002 - method signature must match base
    ) -> list[BaseInputs]:
        raise RuntimeError


def test_schema_matches_returns_false_on_incompatible_model() -> None:
    """A model with incompatible fields does not match the schema."""

    class Expected(BaseInputs):
        x: int

    class Unrelated(BaseInputs):
        y: str

    assert _schema_matches(Expected, Unrelated(y='hi')) is False


def test_validate_raw_inputs_coerces_compatible_base_inputs() -> None:
    """A BaseInputs already of the correct type is appended directly."""

    class Target(BaseInputs):
        x: int

    instance = Target(x=7)
    result = _validate_raw_inputs([instance], Target)
    assert len(result) == 1
    assert result[0] is instance  # passed through unchanged, not re-validated
    assert result[0].x == 7


def test_retrieve_instance_inputs_raises_on_collect_error() -> None:
    pc = {'p': {'foo': 'bar'}}
    with pytest.raises(RuntimeError):
        _retrieve_instance_inputs('p', 0, BadInst(), pc, [])


def test_validate_raw_inputs_wrong_model() -> None:
    class S(BaseInputs):
        a: int

    class Other(BaseInputs):
        b: int

    with pytest.raises(pydantic_core.ValidationError):
        _validate_raw_inputs([Other(b=3)], S)


def test_finalize_provider_contexts_error_path() -> None:
    class F(_ProviderBase):
        def create_context(self) -> BaseContext:
            return BaseContext()

        def finalize_context(  # type: ignore[override]
            self,
            _own_context: BaseModel,
            _received_inputs: list[object],
            _all_providers: list[tuple[str, object, type[BaseModel] | None]],
            _provider_index: int,
        ) -> BaseModel:
            raise RuntimeError

    with pytest.raises(RuntimeError):
        finalize_provider_contexts(
            [('p', {})],
            [F()],
            {'p': [1]},  # type: ignore[arg-type]
            {},
            [],
        )


def test_load_and_validate_template_handles_corrupt_file(
    tmp_path: Path,
):
    """UnicodeDecodeError during template read should remove mapping."""
    # write invalid UTF-8 bytes
    template_file = tmp_path / 'bad.txt'
    template_file.write_bytes(b'\xff\xfe\xff')

    providers = Providers()
    providers.file_mappings['dest'] = TemplateMapping(source_template='bad.txt')

    result = _load_and_validate_template(template_file, providers, 'dest')
    assert result is None
    assert 'dest' not in providers.file_mappings
