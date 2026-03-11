from pydantic import BaseModel

from repolish import BaseContext, Provider, ProviderEntry
from tests.providers_inputs.shared import InputA


# ProviderB does not accept inputs itself; its generic parameter is
# `BaseContext` for context and `BaseModel` for inputs (the latter
# represents "no schema").
class ProviderB(Provider[BaseContext, BaseModel]):
    def create_context(self) -> BaseContext:
        return BaseContext()

    def provide_inputs(
        self,
        own_context: BaseModel,  # noqa: ARG002 - method signature must match base
        all_providers: list[ProviderEntry],
        provider_index: int,  # noqa: ARG002 - method signature must match base
    ) -> list[BaseModel]:
        # only send an InputA if some provider declares that schema
        for entry in all_providers:
            if entry.input_type is InputA:
                return [InputA(prob_a_input='provider_b')]
        return []
