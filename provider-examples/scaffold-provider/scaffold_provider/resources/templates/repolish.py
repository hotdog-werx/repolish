"""ScaffoldProvider - multi-scenario provider for the integration test suite.

Exercises file lifecycle behaviors so the integration tests can drive them
through real ``repolish apply`` / ``repolish apply --check`` invocations:

- ``README.md`` is a regular template: always overwritten on apply.
- ``SETUP.md`` is CREATE_ONLY: seeded once, never overwritten after that.
- ``CONFIG.md`` is CREATE_ONLY but only materialised when
  ``include_optional_config: true`` is set in the consumer's ``repolish.yaml``.
- ``NOTICE.md`` is a Jinja-rendered file that always renders from
  ``NOTICE.md.jinja``.  Demonstrates ``{{ project_name }}`` and
  ``{{ _provider.major_version }}`` Jinja variable access, and Unicode
  content handling.
- ``config.yml`` is a mapped file selected by ``config_variant`` ('a', 'b', or
  'none').  Demonstrates conditional ``_repolish.*`` source selection.
- ``.github/workflows/ci.yml`` is a nested mapped file enabled by
  ``include_ci_workflow: true``.  Demonstrates mapping from a subdirectory.
"""

from repolish import (
    BaseContext,
    BaseInputs,
    FileMode,
    Provider,
    Symlink,
    TemplateMapping,
)


class Ctx(BaseContext):
    """Context for the scaffold provider."""

    project_name: str = 'scaffold-project'
    include_optional_config: bool = False
    # 'a' or 'b' selects the corresponding _repolish.config-*.yml source;
    # any other value (e.g. 'none') disables the mapping entirely.
    config_variant: str = 'none'
    include_ci_workflow: bool = False


class ScaffoldProvider(Provider[Ctx, BaseInputs]):
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
        if context.config_variant in ('a', 'b'):
            mappings['config.yml'] = f'_repolish.config-{context.config_variant}.yml'
        if context.include_ci_workflow:
            mappings['.github/workflows/ci.yml'] = '.github/workflows/_repolish.ci-github.yml'
        return mappings

    def create_default_symlinks(self, context: Ctx) -> list[Symlink]:
        """Create a few symlinks to verify they they work."""
        return [
            Symlink(
                source='configs/some-config.yaml',
                target='symlink-config.yaml',
            ),
        ]


__version__ = '0.1.0'

__all__ = ['ScaffoldProvider', '__version__']
