"""ScaffoldProvider - multi-scenario provider for the integration test suite.

Exercises file lifecycle behaviors so the integration tests can drive them
through real ``repolish apply`` / ``repolish apply --check`` invocations:

- ``README.md`` is a regular template: always overwritten on apply.
- ``SETUP.md`` is CREATE_ONLY: seeded once, never overwritten after that.
- ``CONFIG.md`` is CREATE_ONLY but only materialised when
  ``include_optional_config: true`` is set in the consumer's ``repolish.yaml``.
"""

from pydantic import BaseModel

from repolish import BaseContext, FileMode, Provider, TemplateMapping


class Ctx(BaseContext):
    """Context for the scaffold provider."""

    project_name: str = 'scaffold-project'
    include_optional_config: bool = False


class ScaffoldProvider(Provider[Ctx, BaseModel]):
    """Multi-purpose provider covering create-only, optional mappings, and anchors."""

    def create_anchors(self, context: Ctx) -> dict[str, str]:
        """Return the project-name anchor rendered into README.md."""
        return {'scaffold-project-name': context.project_name}

    def create_file_mappings(
        self,
        context: Ctx,
    ) -> dict[str, str | TemplateMapping | None]:
        """Map destination paths to template sources.

        `SETUP.md` uses CREATE_ONLY: the loader seeds it on the first
        apply and skips it on every subsequent run.  ``CONFIG.md`` adds the
        same behaviour but only when ``include_optional_config`` is enabled.
        """
        mappings: dict[str, str | TemplateMapping | None] = {
            'SETUP.md': TemplateMapping(
                '_repolish.setup.md',
                None,
                FileMode.CREATE_ONLY,
            ),
        }
        if context.include_optional_config:
            mappings['CONFIG.md'] = TemplateMapping(
                '_repolish.optional-config.md',
                None,
                FileMode.CREATE_ONLY,
            )
        return mappings
