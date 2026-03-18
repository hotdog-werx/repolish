from devkit.python.repolish.models import (
    PythonProviderContext,
    PythonProviderInputs,
)
from devkit.workspace.repolish.models import (
    WorkspaceProviderInputs,
)

from repolish import (
    BaseInputs,
    Provider,
    ProviderEntry,
    TemplateMapping,
    override,
)


class PythonProvider(Provider[PythonProviderContext, PythonProviderInputs]):
    """PythonProvider repolish provider."""

    @override
    def create_context(self) -> PythonProviderContext:
        """Return the initial context for this provider.

        The base :class:`~repolish.loader.models.Provider` implementation
        will attempt to construct the context automatically using the
        no-argument constructor of the type parameter.  This stub is
        provided mostly for documentation; you can safely remove it if the
        model has sensible defaults.  Override the method when you need to
        pass explicit arguments or perform other initialization.
        """
        return PythonProviderContext()

    @override
    def provide_inputs(
        self,
        own_context: PythonProviderContext,  # noqa: ARG002
        all_providers: list[ProviderEntry],  # noqa: ARG002
        provider_index: int,  # noqa: ARG002
    ) -> list[BaseInputs]:
        """Broadcast data to other providers that declare a matching input schema.

        Return a list of Pydantic model instances destined for other providers.
        The loader routes each item to every provider whose
        ``get_inputs_schema()`` matches the item's type.  Return an empty list
        if this provider has nothing to share.
        """
        member_name = own_context._provider.monorepo.member_name
        return [
            WorkspaceProviderInputs(
                add_to_member=f'python: This is a workspace member! {member_name}',
                add_to_root=f'python: This is the root of the monorepo! {member_name}',
            ),
        ]

    @override
    def finalize_context(
        self,
        own_context: PythonProviderContext,
        received_inputs: list[PythonProviderInputs],  # noqa: ARG002
        all_providers: list[ProviderEntry],  # noqa: ARG002
        provider_index: int,  # noqa: ARG002
    ) -> PythonProviderContext:
        """Merge inputs received from other providers into this context.

        ``received_inputs`` contains every ``PythonProviderInputs`` payload
        delivered to this provider by upstream ``provide_inputs`` calls.
        Inspect the list, update ``own_context`` as needed, and return it.
        If this provider does not consume inputs from others, just return
        ``own_context`` unchanged.
        """
        return own_context

    @override
    def get_inputs_schema(self) -> type[PythonProviderInputs]:
        """Declare the Pydantic model class this provider accepts as input.

        The loader uses this to route payloads emitted by other providers'
        ``provide_inputs`` to this provider's ``finalize_context``.
        """
        return PythonProviderInputs

    @override
    def create_file_mappings(
        self,
        context: PythonProviderContext,  # noqa: ARG002
    ) -> dict[str, str | TemplateMapping | None]:
        """Map destination paths to template sources.

        Keys are POSIX paths relative to the consumer repo root.  Values can
        be:
        - a string  → path to the source template inside ``resources/templates``
        - a ``TemplateMapping``  → for CREATE_ONLY, DELETE, or KEEP semantics
        - ``None``   → omit the file (no-op)

        Use ``self.templates_root`` to discover templates dynamically, e.g.:
            workflows = (self.templates_root / 'repolish' / '.github' / 'workflows').glob('*.yaml')
        """
        return {}

    @override
    def create_anchors(
        self,
        context: PythonProviderContext,  # noqa: ARG002
    ) -> dict[str, str]:
        """Supply anchor replacement values for this provider's templates.

        Anchors are named placeholders inside template files that are replaced
        before Jinja rendering.  Return a mapping of anchor name to
        replacement string.  Return an empty dict if no anchors are needed.
        """
        return {}
