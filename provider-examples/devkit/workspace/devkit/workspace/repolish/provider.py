from devkit.workspace.repolish.models import (
    WorkspaceProviderContext,
    WorkspaceProviderInputs,
)
from typing_extensions import override

from repolish import (
    BaseInputs,
    FinalizeContextOptions,
    ProvideInputsOptions,
    Provider,
    TemplateMapping,
)


class WorkspaceProvider(
    Provider[WorkspaceProviderContext, WorkspaceProviderInputs],
):
    """WorkspaceProvider repolish provider."""

    @override
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[WorkspaceProviderContext],
    ) -> list[BaseInputs]:
        """Broadcast data to other providers that declare a matching input schema.

        Return a list of Pydantic model instances destined for other providers.
        The loader routes each item to every provider whose
        ``get_inputs_schema()`` matches the item's type.  Return an empty list
        if this provider has nothing to share.
        """
        mode = opt.own_context.repolish.workspace.mode
        if mode == 'root':
            # The root provider collects messages from members; it has nothing
            # to report to itself.
            return []
        member_name = opt.own_context.repolish.provider.session.member_name
        member_path = opt.own_context.repolish.provider.session.member_path
        payload = WorkspaceProviderInputs(
            add_to_member=f'workspace: This is a workspace member! {member_name}',
            add_to_root=f'workspace: This is the root of the monorepo! {member_name}',
            member_path=member_path,
        )
        return [payload]

    @override
    def finalize_context(
        self,
        opt: FinalizeContextOptions[
            WorkspaceProviderContext,
            WorkspaceProviderInputs,
        ],
    ) -> WorkspaceProviderContext:
        """Merge inputs received from other providers into this context.

        ``opt.received_inputs`` contains every ``WorkspaceProviderInputs`` payload
        delivered to this provider by upstream ``provide_inputs`` calls.
        Inspect the list, update ``opt.own_context`` as needed, and return it.
        If this provider does not consume inputs from others, just return
        ``opt.own_context`` unchanged.
        """
        opt.own_context.root_file_messages = [
            inp.add_to_root for inp in opt.received_inputs if inp.add_to_root is not None
        ]
        opt.own_context.root_file_sources = sorted(
            {inp.member_path for inp in opt.received_inputs if inp.member_path},
        )
        return opt.own_context

    @override
    def create_file_mappings(
        self,
        context: WorkspaceProviderContext,
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
