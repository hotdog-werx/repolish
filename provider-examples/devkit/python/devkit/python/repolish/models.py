from repolish import BaseContext, BaseInputs


class PythonProviderContext(BaseContext):
    """Context for the PythonProvider."""


class PythonProviderInputs(BaseInputs):
    """Inputs for the PythonProvider.

    Fields declared here can be populated by other providers via
    ``provide_inputs`` and delivered to this provider's ``finalize_context``.
    """
