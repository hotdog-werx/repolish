from pydantic import BaseModel

from repolish import BaseContext, Provider
from repolish.providers.models import BaseInputs, ProvideInputsOptions
from tests.providers_inputs.shared import InputA


# ProviderB does not accept inputs itself; its generic parameter is
# `BaseContext` for context and `BaseModel` for inputs (the latter
# represents "no schema").
class ProviderB(Provider[BaseContext, BaseInputs]):
    def create_context(self) -> BaseContext:
        return BaseContext()

    def provide_inputs(
        self,
        opt: ProvideInputsOptions[BaseContext],
    ) -> list[BaseInputs]:
        # only send an InputA if some provider declares that schema
        for entry in opt.all_providers:
            if entry.input_type is InputA:
                return [InputA(prob_a_input='provider_b')]
        return []
