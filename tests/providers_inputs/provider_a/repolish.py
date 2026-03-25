from repolish.providers.models import FinalizeContextOptions, Provider
from tests.providers_inputs.shared import CtxA, InputA


class ProviderA(Provider[CtxA, InputA]):
    def create_context(self):
        return CtxA()

    def get_inputs_schema(self):
        return InputA

    def finalize_context(
        self,
        opt: FinalizeContextOptions[CtxA, InputA],
    ) -> CtxA:
        if opt.received_inputs:
            opt.own_context.prov_a_value = opt.received_inputs[0].prob_a_input
        return opt.own_context
