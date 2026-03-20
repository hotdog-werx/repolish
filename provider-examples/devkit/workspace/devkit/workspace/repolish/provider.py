from devkit.workspace.repolish.models import (
    WorkspaceProviderContext,
    WorkspaceProviderInputs,
)

from repolish import (
    BaseInputs,
    Provider,
    ProviderEntry,
    TemplateMapping,
    override,
)


class WorkspaceProvider(
    Provider[WorkspaceProviderContext, WorkspaceProviderInputs],
):
    """WorkspaceProvider repolish provider."""

    @override
    def provide_inputs(
        self,
        own_context: WorkspaceProviderContext,
        all_providers: list[ProviderEntry],  # noqa: ARG002
        provider_index: int,  # noqa: ARG002
    ) -> list[BaseInputs]:
        """Broadcast data to other providers that declare a matching input schema.

        Return a list of Pydantic model instances destined for other providers.
        The loader routes each item to every provider whose
        ``get_inputs_schema()`` matches the item's type.  Return an empty list
        if this provider has nothing to share.
        """
        mode = own_context.repolish.workspace.mode
        if mode == 'root':
            # The root provider collects messages from members; it has nothing
            # to report to itself.
            return []
        member_name = own_context.repolish.provider.session.member_name
        payload = WorkspaceProviderInputs(
            add_to_member=f'workspace: This is a workspace member! {member_name}',
            add_to_root=f'workspace: This is the root of the monorepo! {member_name}',
        )
        return [payload]

    @override
    def finalize_context(
        self,
        own_context: WorkspaceProviderContext,
        received_inputs: list[WorkspaceProviderInputs],
        all_providers: list[ProviderEntry],  # noqa: ARG002
        provider_index: int,  # noqa: ARG002
    ) -> WorkspaceProviderContext:
        """Merge inputs received from other providers into this context.

        ``received_inputs`` contains every ``WorkspaceProviderInputs`` payload
        delivered to this provider by upstream ``provide_inputs`` calls.
        Inspect the list, update ``own_context`` as needed, and return it.
        If this provider does not consume inputs from others, just return
        ``own_context`` unchanged.
        """
        own_context.root_file_messages = [inp.add_to_root for inp in received_inputs if inp.add_to_root is not None]
        return own_context

    @override
    def create_file_mappings(
        self,
        context: WorkspaceProviderContext,  # noqa: ARG002
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
        return {
            'root_file.md': 'root_file.md',
        }
