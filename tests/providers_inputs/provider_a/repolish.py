from repolish.providers.models import Provider, ProviderEntry
from tests.providers_inputs.shared import CtxA, InputA


class ProviderA(Provider[CtxA, InputA]):
    def create_context(self):
        return CtxA()

    def get_inputs_schema(self):
        return InputA

    def finalize_context(
        self,
        own_context: CtxA,
        received_inputs: list[InputA],
        all_providers: list[ProviderEntry],  # noqa: ARG002 - method signature must match base
        provider_index: int,  # noqa: ARG002 - method signature must match base
    ) -> CtxA:
        if received_inputs:
            own_context.prov_a_value = received_inputs[0].prob_a_input
        return own_context
