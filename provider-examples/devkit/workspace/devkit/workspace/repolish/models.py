from repolish import BaseContext, BaseInputs


class WorkspaceProviderContext(BaseContext):
    """Context for the WorkspaceProvider."""


class WorkspaceProviderInputs(BaseInputs):
    """Inputs for the WorkspaceProvider.

    Fields declared here can be populated by other providers via
    ``provide_inputs`` and delivered to this provider's ``finalize_context``.
    """
