from pydantic import BaseModel


class CtxA(BaseModel):
    prov_a_value: str = 'provider_a'


class InputA(BaseModel):
    prob_a_input: str
