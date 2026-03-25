from repolish.providers.models import (
    BaseContext,
    BaseInputs,
    ProvideInputsOptions,
    Provider,
)
from tests.providers_inputs.shared import InputA


# ProviderC does not itself accept inputs
class CtxC(BaseContext):
    pass


class ProviderC(Provider[CtxC, InputA]):
    def create_context(self) -> CtxC:
        return CtxC()

    def provide_inputs(
        self,
        opt: ProvideInputsOptions[CtxC],  # noqa: ARG002 - parameter unused
    ) -> list[InputA]:
        return [InputA(prob_a_input='provider_c')]
