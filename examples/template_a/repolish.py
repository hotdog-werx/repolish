from pydantic import BaseModel

from repolish import (
    BaseContext,
    FileMode,
    Provider,
    TemplateMapping,
)  # re-exported for simple API


class Ctx(BaseContext):
    """Example provider context for the `template_a` example."""

    package_name: str = 'my-project'
    alias: str = ''


class TemplateAProvider(Provider[Ctx, BaseModel]):
    """Class-based example provider for the `template_a` example."""

    def create_context(self) -> Ctx:
        """Return this provider's Pydantic context model."""
        return Ctx(alias=self.alias)

    def create_file_mappings(
        self,
        context: Ctx,  # noqa: ARG002 - context is not used in this example
    ) -> dict[str, str | TemplateMapping | None]:
        """Return file mappings for this example.

        Uses a `TemplateMapping` with `FileMode.DELETE` to mark
        `old_file.txt` for deletion.
        """
        return {'old_file.txt': TemplateMapping(None, None, FileMode.DELETE)}

    def create_anchors(
        self,
        context: Ctx,  # noqa: ARG002 - context is not used in this example
    ) -> dict[str, str]:
        """Return anchor replacements used by the example provider."""
        return {'extra-deps': '\nrequests = "^2.30"\n'}
