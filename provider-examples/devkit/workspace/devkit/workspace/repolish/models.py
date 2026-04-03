from pydantic import Field

from repolish import BaseContext, BaseInputs


class WorkspaceProviderContext(BaseContext):
    """Context for the WorkspaceProvider."""

    root_file_messages: list[str] = Field(default_factory=list)
    root_file_sources: list[str] = Field(default_factory=list)
    """Repo-relative member paths that contributed inputs, in sorted order."""


class WorkspaceProviderInputs(BaseInputs):
    """Inputs for the WorkspaceProvider.

    Fields declared here can be populated by other providers via
    ``provide_inputs`` and delivered to this provider's ``finalize_context``.
    """

    add_to_root: str | None = None
    add_to_member: str | None = None
    member_path: str = ''
    """Repo-relative path of the member that emitted this input."""
