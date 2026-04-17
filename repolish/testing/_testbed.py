"""Core :class:`ProviderTestBed` for exercising provider hooks in isolation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

from jinja2 import Environment, StrictUndefined, select_autoescape
from pydantic import BaseModel

from repolish.misc import ctx_to_dict
from repolish.providers.models.context import BaseContext, BaseInputs
from repolish.providers.models.provider import (
    FinalizeContextOptions,
    ProvideInputsOptions,
    Provider,
    ProviderEntry,
    call_provider_method,
)
from repolish.testing._context import make_context

if TYPE_CHECKING:
    from collections.abc import Sequence

CtxT = TypeVar('CtxT', bound=BaseContext)
InpT = TypeVar('InpT', bound=BaseModel)


def _locate_templates_root(provider_cls: type) -> Path:
    """Discover the ``resources/templates`` directory for *provider_cls*.

    Walks the module hierarchy from the provider's ``__module__`` to find
    the package root, then looks for ``resources/templates`` underneath it.
    This mirrors what the resource linker does at install time.
    """
    mod = importlib.import_module(provider_cls.__module__)
    mod_file = getattr(mod, '__file__', None)
    if mod_file is None:  # pragma: no cover
        msg = f'cannot locate source for {provider_cls.__module__}'
        raise RuntimeError(msg)

    # Walk up from the provider module until we find a resources/templates dir.
    pkg_dir = Path(mod_file).resolve().parent
    # The provider module is typically at <pkg>/repolish/provider.py or
    # <pkg>/repolish/provider/__init__.py.  Walk up to the package root.
    for ancestor in [pkg_dir, *pkg_dir.parents]:
        candidate = ancestor / 'resources' / 'templates'
        if candidate.is_dir():
            return candidate
        # Stop at the site-packages or filesystem root.
        if (ancestor / 'pyproject.toml').exists():
            break
    msg = f'cannot find resources/templates for {provider_cls.__name__}'
    raise RuntimeError(msg)


@dataclass
class ProviderTestBed(Generic[CtxT, InpT]):
    """Lightweight harness for testing provider hooks without a full pipeline.

    Instantiates the provider, injects a synthetic context, and exposes
    methods to exercise each lifecycle hook in isolation.

    Args:
        provider_class: The concrete :class:`Provider` subclass to test.
        context: An instance of the provider's context model.  If ``None``,
            the provider's :meth:`create_context` is called.
        mode: Workspace mode (``'standalone'``, ``'root'``, ``'member'``).
            Controls mode-handler dispatch and the ``repolish.workspace.mode``
            value injected into the context.
        templates_root: Explicit path to ``resources/templates``.  Auto-detected
            from the provider class when omitted.
        alias: Provider alias injected into the instance metadata.
        version: Provider version injected into the instance metadata.
    """

    provider_class: type[Provider[CtxT, InpT]]
    context: CtxT | None = None
    mode: Literal['root', 'member', 'standalone'] = 'standalone'
    templates_root: Path | None = None
    alias: str = 'test-provider'
    version: str = '0.1.0'

    # Private, set in __post_init__
    _instance: Provider[CtxT, InpT] = field(init=False, repr=False)
    _resolved_context: CtxT = field(init=False, repr=False)
    _templates_root: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._instance = self.provider_class()
        self._templates_root = (
            self.templates_root if self.templates_root is not None else _locate_templates_root(self.provider_class)
        )
        # Inject metadata that the loader normally sets.
        self._instance.templates_root = self._templates_root
        self._instance.alias = self.alias
        self._instance.version = self.version

        ctx = self.context if self.context is not None else self._instance.create_context()

        # Ensure the repolish namespace reflects the requested mode.
        if hasattr(ctx, 'repolish'):
            ctx.repolish = make_context(
                mode=self.mode,
                alias=self.alias,
                version=self.version,
            )
        self._resolved_context = ctx

    @property
    def resolved_context(self) -> CtxT:
        """The context object with ``repolish`` namespace injected."""
        return self._resolved_context

    # -- Lifecycle hooks --

    def file_mappings(self) -> dict[str, str | Any | None]:
        """Call ``create_file_mappings`` on the provider (or mode handler)."""
        return cast(
            'dict[str, str | Any | None]',
            call_provider_method(
                self._instance,
                'create_file_mappings',
                self._resolved_context,
            ),
        )

    def anchors(self) -> dict[str, str]:
        """Call ``create_anchors`` on the provider (or mode handler)."""
        return cast(
            'dict[str, str]',
            call_provider_method(
                self._instance,
                'create_anchors',
                self._resolved_context,
            ),
        )

    def symlinks(self) -> list:
        """Call ``create_default_symlinks`` on the provider (or mode handler)."""
        return cast('list', self._instance.create_default_symlinks())

    def promote_file_mappings(self) -> dict[str, str | Any | None]:
        """Call ``promote_file_mappings`` on the provider (or mode handler)."""
        return cast(
            'dict[str, str | Any | None]',
            call_provider_method(
                self._instance,
                'promote_file_mappings',
                self._resolved_context,
            ),
        )

    def provide_inputs(
        self,
        *,
        all_providers: list[ProviderEntry] | None = None,
        provider_index: int = 0,
    ) -> Sequence[BaseInputs]:
        """Call ``provide_inputs`` on the provider (or mode handler).

        Args:
            all_providers: Provider entries visible during input emission.
                Defaults to a single-element list containing this provider.
            provider_index: Position in the load order.
        """
        if all_providers is None:
            all_providers = [self._make_self_entry()]
        opt = ProvideInputsOptions(
            own_context=self._resolved_context,
            all_providers=all_providers,
            provider_index=provider_index,
        )
        return cast(
            'Sequence[BaseInputs]',
            call_provider_method(self._instance, 'provide_inputs', opt),
        )

    def finalize(
        self,
        received_inputs: list[InpT],
        *,
        all_providers: list[ProviderEntry] | None = None,
        provider_index: int = 0,
    ) -> CtxT:
        """Call ``finalize_context`` on the provider (or mode handler).

        Args:
            received_inputs: Payloads from other providers to merge.
            all_providers: Provider entries visible during finalization.
            provider_index: Position in the load order.

        Returns:
            The finalized context.
        """
        if all_providers is None:
            all_providers = [self._make_self_entry()]
        opt = FinalizeContextOptions(
            own_context=self._resolved_context,
            received_inputs=received_inputs,
            all_providers=all_providers,
            provider_index=provider_index,
        )
        result = cast(
            'CtxT',
            call_provider_method(self._instance, 'finalize_context', opt),
        )
        self._resolved_context = result
        return result

    # -- Template rendering --

    def render(
        self,
        template_name: str,
        *,
        extra_context: dict[str, Any] | None = None,
    ) -> str:
        """Render a single template file and return the result as a string.

        The template is loaded from ``resources/templates/repolish/`` under
        the provider's package.  The context is flattened to a dict via
        :func:`ctx_to_dict` — the same path production rendering uses.

        Args:
            template_name: Relative path under ``templates/repolish/``,
                e.g. ``'mise.toml.jinja'`` or ``'.github/workflows/ci.yml'``.
            extra_context: Optional additional variables merged on top of
                the provider context (useful for ``TemplateMapping.context``
                values).

        Raises:
            FileNotFoundError: If the template file does not exist.
            jinja2.UndefinedError: If the template references missing variables.
        """
        template_path = self._templates_root / 'repolish' / template_name
        if not template_path.exists():
            msg = f'template not found: {template_path}'
            raise FileNotFoundError(msg)

        env = self._make_env()
        ctx = ctx_to_dict(self._resolved_context)
        if extra_context:
            ctx.update(extra_context)

        txt = template_path.read_text(encoding='utf-8')
        return env.from_string(txt).render(**ctx)

    def render_all(
        self,
        *,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Render every file in ``create_file_mappings`` plus auto-discovered templates.

        Returns a ``{dest_path: rendered_content}`` dict.  Jinja files
        (``.jinja`` extension) are rendered; static files are returned as-is.
        Templates with a ``_repolish.`` prefix are only included when they
        appear in ``create_file_mappings``.

        Auto-discovered templates (files in ``templates/repolish/`` without
        the ``_repolish.`` prefix) are included automatically, mirroring
        production behavior.

        Args:
            extra_context: Additional variables merged on top of the context.
        """
        mappings = self.file_mappings()
        template_dir = self._templates_root / 'repolish'

        env = self._make_env()
        ctx = ctx_to_dict(self._resolved_context)
        if extra_context:
            ctx.update(extra_context)

        result = self._render_mapped(env, ctx, mappings, template_dir)
        self._render_auto_discovered(env, ctx, mappings, template_dir, result)
        return result

    def _render_mapped(
        self,
        env: Environment,
        ctx: dict,
        mappings: dict,
        template_dir: Path,
    ) -> dict[str, str]:
        """Render explicitly mapped files."""
        result: dict[str, str] = {}
        for dest, source in mappings.items():
            if source is None:
                continue
            source_name = source if isinstance(source, str) else source.source_template
            if source_name is None:
                continue
            src_path = template_dir / source_name
            if src_path.exists():
                result[dest] = self._render_one(env, src_path, ctx)
        return result

    def _render_auto_discovered(
        self,
        env: Environment,
        ctx: dict,
        mappings: dict,
        template_dir: Path,
        result: dict[str, str],
    ) -> None:
        """Add auto-discovered non-prefixed templates to *result*."""
        if not template_dir.is_dir():
            return
        mapped_sources = {(v if isinstance(v, str) else v.source_template) for v in mappings.values() if v is not None}
        for src in template_dir.rglob('*'):
            if src.is_dir():
                continue
            rel = src.relative_to(template_dir).as_posix()
            if any(p.startswith('_repolish.') for p in Path(rel).parts):
                continue
            if rel in result or rel in mapped_sources:
                continue
            result[rel] = self._render_one(env, src, ctx)

    # -- Private helpers --

    def _make_env(self) -> Environment:
        return Environment(
            autoescape=select_autoescape(
                ['html', 'xml'],
                default_for_string=False,
            ),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def _render_one(self, env: Environment, src: Path, ctx: dict) -> str:
        """Render or read a single template file."""
        try:
            txt = src.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            return src.read_bytes().decode('latin-1')

        if src.suffix == '.jinja':
            return env.from_string(txt).render(**ctx)
        return txt

    def _make_self_entry(self) -> ProviderEntry:
        return ProviderEntry(
            provider_id=self.alias,
            alias=self.alias,
            inst_type=self.provider_class,
            context=self._resolved_context,
            context_type=type(self._resolved_context),
            input_type=self._instance.get_inputs_schema(),
        )
