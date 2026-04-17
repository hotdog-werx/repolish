from repolish.providers.models import (
    BaseContext,
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
        opt: ProvideInputsOptions[CtxC],
    ) -> list[InputA]:
        return [InputA(prob_a_input='provider_c')]
