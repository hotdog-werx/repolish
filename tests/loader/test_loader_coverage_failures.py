from pathlib import Path

import pydantic_core
import pytest
from pydantic import BaseModel

from repolish.hydration.rendering import _load_and_validate_template
from repolish.loader.models import (
    Provider as _ProviderBase,
)
from repolish.loader.models import (
    Providers,
    TemplateMapping,
)
from repolish.loader.three_phase import (
    _retrieve_instance_inputs,
    _retrieve_module_inputs,
    _validate_raw_inputs,
    finalize_provider_contexts,
)


class BadInst(_ProviderBase):
    def get_provider_name(self) -> str:
        return 'i'

    def create_context(self) -> BaseModel:
        raise ValueError

    def collect_provider_inputs(
        self,
        _own_context: BaseModel,
        _all_providers: list[tuple[str, object]],
        _provider_index: int,
    ) -> dict[str, object]:
        raise RuntimeError


def test_retrieve_instance_inputs_raises_on_collect_error() -> None:
    pc = {'p': {'foo': 'bar'}}
    with pytest.raises(RuntimeError):
        _retrieve_instance_inputs('p', 0, BadInst(), pc, [])


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


def test_validate_raw_inputs_wrong_model() -> None:
    class S(BaseModel):
        a: int

    class Other(BaseModel):
        b: int

    with pytest.raises(pydantic_core.ValidationError):
        _validate_raw_inputs([Other(b=3)], S)


def test_finalize_provider_contexts_error_path() -> None:
    class F(_ProviderBase):
        def get_provider_name(self) -> str:
            return 'f'

        def create_context(self) -> BaseModel:
            return BaseModel()

        def finalize_context(
            self,
            _own_context: BaseModel,
            _received_inputs: list[object],
            _all_providers: list[tuple[str, object]],
            _provider_index: int,
        ) -> BaseModel:
            raise RuntimeError

    with pytest.raises(RuntimeError):
        finalize_provider_contexts(
            [('p', {})],
            [F()],
            {'p': [1]},
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
