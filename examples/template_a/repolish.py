from pydantic import BaseModel

from repolish import (
    FileMode,
    Provider,
    TemplateMapping,
)  # re-exported for simple API


class Ctx(BaseModel):
    """Example provider context for the `template_a` example."""

    package_name: str = 'my-project'


class TemplateAProvider(Provider[Ctx, BaseModel]):
    """Class-based example provider for the `template_a` example."""

    def get_provider_name(self) -> str:
        """Return the provider identifier for this example."""
        return 'template_a'

    def create_context(self) -> Ctx:
        """Return this provider's Pydantic context model."""
        return Ctx()

    def create_file_mappings(
        self,
        _ctx: dict[str, object] | None = None,
    ) -> dict[str, str | TemplateMapping]:
        """Return file mappings for this example.

        Uses a `TemplateMapping` with `FileMode.DELETE` to mark
        `old_file.txt` for deletion.
        """
        return {'old_file.txt': TemplateMapping(None, None, FileMode.DELETE)}

    def create_anchors(
        self,
        _ctx: dict[str, object] | None = None,
    ) -> dict[str, str]:
        """Return anchor replacements used by the example provider."""
        return {'extra-deps': '\nrequests = "^2.30"\n'}
