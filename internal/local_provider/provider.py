"""Project-local repolish provider (installable tier).

Unlike the flat tier this is a real installed package: add sibling modules
here and import them normally (e.g. `from local_provider.helpers import x`).
`templates/repolish.py` re-exports LocalProvider from here — that file is
what repolish.yaml's provider_root points at and must not grow code itself.
"""

from collections.abc import Callable

from local_provider.docs_insertions import DOCS_INSERTION_FILES, DOCS_INSERTION_REGISTRY
from local_provider.mise_tasks import collect_mise_tasks
from local_provider.uvtb import env_site_packages
from repolish import (
    BaseContext,
    BaseInputs,
    BlockContext,
    FastLaneDeclaration,
    FastLaneSpec,
    Provider,
    TemplateMapping,
)
from repolish.hydration.rendering import render_text
from repolish.providers.models.context import RepolishContext


class LocalProviderContext(BaseContext):
    """Context shared across this provider's contributions."""


_DEV_TASKS_TEMPLATE = """{% for group in groups %}{% if not loop.first %}
{% endif %}**{{ group.name }}**

| Task | Description |
| ----- | ----------- |
{% for task in group.tasks %}| `{{ task.name }}` | {{ task.description | replace('|', '\\|') }} |
{% endfor %}{% endfor %}"""


def _dev_tasks(*, context: BlockContext) -> str:
    """Insertion body: the repo's mise tasks as a Jinja-rendered table."""
    return render_text(
        _DEV_TASKS_TEMPLATE,
        {'groups': collect_mise_tasks(context.repolish.workspace.root_dir)},
        filename='dev-tasks.md.jinja',
    )


def _venv_spec(repolish: RepolishContext) -> FastLaneSpec:
    """Map `ty.toml` with the toolbox `repolish` env's site-packages path.

    The path is content-addressed by uv-toolbox, so it is resolved per run
    rather than hardcoded. Relative when the venv lives in the project
    (the `venv_path` config), absolute if it ever moves to the central
    cache.
    """
    root = repolish.workspace.root_dir
    site = env_site_packages('repolish', root)
    rel = site.relative_to(root).as_posix() if site.is_relative_to(root) else site.as_posix()
    return FastLaneSpec(
        file_mappings={
            'ty.toml': TemplateMapping(
                '_repolish.ty.toml.jinja',
                extra_context={'venv_site_packages': rel},
            ),
        },
    )


class LocalProvider(Provider[LocalProviderContext, BaseInputs]):
    """Project-local provider: quick templates and insertion functions."""

    def create_file_insertions(
        self,
        context: LocalProviderContext,  # noqa: ARG002 - mirrors the base hook
    ) -> list[str]:
        """Declare the files repolish may fill: README plus the docs tables.

        No `@override`: the repo floor is 3.11 (ty assumes it from the root
        pyproject) and product code skips the decorator for the same reason.
        """
        return ['README.md', *DOCS_INSERTION_FILES]

    def create_insertion_registry(
        self,
        context: LocalProviderContext,  # noqa: ARG002 - mirrors the base hook
    ) -> dict[str, Callable[..., str]]:
        """The shared insertion functions, keyed by marker function name.

        Every file listed by `create_file_insertions` resolves its marker
        blocks against this registry: the README's `dev-tasks` table and
        the docs data tables rendered from product code (see
        docs_insertions).
        """
        return {'dev-tasks': _dev_tasks, **DOCS_INSERTION_REGISTRY}

    def create_fast_lanes(
        self,
        repolish: RepolishContext,
    ) -> dict[str, FastLaneDeclaration]:
        """Declare the `venv` lane.

        The docs insertions live on the regular hooks (see
        `create_insertion_registry`), not a lane: only the `ty.toml`
        mapping needs the lane's lazy loading to defer resolving the
        toolbox env's site-packages path.
        """
        return {
            'venv': lambda: _venv_spec(repolish),
        }
