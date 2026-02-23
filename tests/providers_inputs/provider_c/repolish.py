from pydantic import BaseModel

from repolish.loader.models import Provider, ProviderEntry
from tests.providers_inputs.shared import InputA


# ProviderC does not itself accept inputs
class CtxC(BaseModel):
    pass


class ProviderC(Provider[CtxC, InputA]):
    def get_provider_name(self):
        return 'c'

    def create_context(self) -> CtxC:
        return CtxC()

    def provide_inputs(
        self,
        own_context: CtxC,  # noqa: ARG002 - method signature must match base
        all_providers: list[ProviderEntry],  # noqa: ARG002 - method signature must match base
        provider_index: int,  # noqa: ARG002 - method signature must match base
    ) -> list[BaseModel]:
        return [InputA(prob_a_input='provider_c')]
