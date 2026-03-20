from repolish.providers.models import BaseContext, BaseInputs


class CtxA(BaseContext):
    prov_a_value: str = 'provider_a'


class InputA(BaseInputs):
    prob_a_input: str
