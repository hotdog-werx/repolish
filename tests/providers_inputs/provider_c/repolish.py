from repolish.loader.models import (
    BaseContext,
    BaseInputs,
    Provider,
    ProviderEntry,
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
        own_context: CtxC,  # noqa: ARG002 - method signature must match base
        all_providers: list[ProviderEntry],  # noqa: ARG002 - method signature must match base
        provider_index: int,  # noqa: ARG002 - method signature must match base
    ) -> list[BaseInputs]:
        return [InputA(prob_a_input='provider_c')]
