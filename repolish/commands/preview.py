"""The preview command: a single-document apply in miniature.

Preview runs the whole apply pipeline over one scratch document — pre-render
directives, the Jinja render, the after-render directive pass (including
insertion-marker adoption), and the insertion stage (``repolish:on`` blocks and
``repolish:insert`` zones) — so template authors can exercise every marker
family without a real project or a full ``repolish apply``.
"""

import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from time import perf_counter
from types import ModuleType
from typing import Any

import yaml
from hotlog import get_logger
from jinja2 import TemplateSyntaxError, UndefinedError
from pydantic import BaseModel, Field

from repolish.console import console
from repolish.directives import DirectivePhase, extract_patterns, process_text
from repolish.directives.insert_zones import (
    InsertZoneDeclaration,
    extract_insert_zone_declarations,
)
from repolish.hydration.rendering import render_text
from repolish.insertions import render_insertions_text
from repolish.reporting import print_command_timings

logger = get_logger(__name__)


class DebugInsertions(BaseModel):
    """Insertion inputs: entry points resolved to renderer callables."""

    functions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            'Function name to entry point (`module:object.attr`); a leading `.` '
            'imports the module from the scratch file directory'
        ),
    )


class DebugConfigSection(BaseModel):
    """The debug file's `config` mapping, typed per supported key."""

    anchors: dict[str, str] = Field(
        default_factory=dict,
        description='Anchor name to replacement text for tag blocks',
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description='Variables exposed to the Jinja render stage',
    )
    insertions: DebugInsertions = Field(
        default_factory=DebugInsertions,
        description='Insertion functions available to the document',
    )


class DebugConfig(BaseModel):
    """Configuration for the repolish-debugger tool."""

    template: str = Field(
        ...,
        description='The template content to process',
    )
    target: str = Field(
        default='',
        description='The target file content to extract patterns from',
    )
    config: DebugConfigSection = Field(
        default_factory=DebugConfigSection,
        description='Configuration object with anchors, context, and insertions',
    )


def command(
    debug_file: Path,
    *,
    show_patterns: bool,
    show_steps: bool,
) -> int:
    """Run the preview preprocessor tool."""
    started = perf_counter()
    try:
        return _run_preview(
            debug_file,
            show_patterns=show_patterns,
            show_steps=show_steps,
        )
    finally:
        # preview debugs a scratch file, not a project config, so the footer
        # is duration-only: no config dir hosts a timings file.
        print_command_timings('preview', (perf_counter() - started) * 1000)


def _load_debug_config(debug_file: Path) -> DebugConfig:
    """Read and validate the scratch YAML document."""
    with Path(debug_file).open(encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return DebugConfig.model_validate(data)


def _run_preview(
    debug_file: Path,
    *,
    show_patterns: bool,
    show_steps: bool,
) -> int:
    """Preview body; :func:`command` wraps this for the timing footer."""
    debug_config = _load_debug_config(debug_file)
    template = debug_config.template
    target = debug_config.target
    section = debug_config.config

    try:
        registry = _build_insertion_registry(section.insertions, debug_file)
    except _EntryPointError as exc:
        logger.exception(
            'preview_insertion_registration_failed',
            error=str(exc),
        )
        return 1

    console.rule('[bold]Debug Preprocessing')
    logger.info(
        'debug_preprocessing_started',
        template_length=len(template),
        target_length=len(target),
        anchors=list(section.anchors),
    )
    console.print()

    if show_patterns:
        _show_patterns(template, debug_file)

    try:
        pre_rendered = process_text(
            template,
            target,
            section.anchors,
            source_path=str(debug_file),
        )
        rendered = render_text(
            pre_rendered,
            section.context,
            filename=debug_file,
        )
    except (UndefinedError, TemplateSyntaxError) as exc:
        logger.exception('preview_render_failed', error=str(exc))
        return 1

    after_rendered = process_text(
        rendered,
        target,
        phase=DirectivePhase.AFTER_RENDER,
        source_path=str(debug_file),
    )
    final, diagnostics = _run_insertion_stage(
        after_rendered,
        template,
        rendered,
        registry,
        debug_file,
    )

    if show_steps:
        _show_stage('Pre-render (what Jinja receives)', pre_rendered)
        _show_stage('Rendered (after Jinja)', rendered)
        _show_stage('After-render directives', after_rendered)

    if diagnostics:
        logger.warning(
            'insertion_diagnostics',
            messages=[diagnostic.message for diagnostic in diagnostics],
        )

    console.rule('[bold]Result')
    console.print(final, markup=False, highlight=False)
    return 0


def _show_patterns(template: str, debug_file: Path) -> None:
    """Print the patterns extracted from the template, per phase."""
    for phase in (DirectivePhase.PRE_RENDER, DirectivePhase.AFTER_RENDER):
        patterns = extract_patterns(
            template,
            phase=phase,
            source_path=str(debug_file),
        )
        console.rule(f'[bold]Extracted Patterns ({phase.value})')
        logger.info(
            'extracted_patterns',
            phase=phase.value,
            tag_blocks=patterns.tag_blocks,
            keep_blocks=patterns.keep_blocks,
            keep_rest=patterns.keep_rest,
            keep_header=patterns.keep_header,
            regexes=patterns.regexes,
            multiregex_blocks=patterns.multiregex_blocks,
            multiregexes=patterns.multiregexes,
        )
        console.print()


def _show_stage(title: str, content: str) -> None:
    """Print one intermediate pipeline stage."""
    console.rule(f'[bold]Stage: {title}')
    console.print(content, markup=False, highlight=False)
    console.print()


class _EntryPointError(Exception):
    """Raised when a declared insertion entry point cannot be resolved."""


def _build_insertion_registry(
    insertions: DebugInsertions,
    debug_file: Path,
) -> dict[str, Callable[..., str]]:
    """Resolve insertion entry points into a renderer registry.

    Each value follows the pyproject script form ``module:object.attr``: the
    module is imported and the dotted attribute path is walked to a callable,
    giving prototype functions the same calling contract a real apply's
    registered renderers meet. A leading ``.`` marks the module as a sibling
    of the scratch file.
    """
    return {name: _resolve_entry_point(name, entry, debug_file) for name, entry in insertions.functions.items()}


def _resolve_entry_point(
    alias: str,
    entry: str,
    debug_file: Path,
) -> Callable[..., str]:
    """Import one entry point and return the callable it names."""
    module_name, marker, attr_path = entry.partition(':')
    if not marker or not module_name or not attr_path:
        msg = f'insertion {alias!r}: expected "module:object", got {entry!r}'
        raise _EntryPointError(msg)

    try:
        module = _import_entry_module(module_name, debug_file)
        target: Any = module
        for attr in attr_path.split('.'):
            target = getattr(target, attr)
    except (AttributeError, ImportError) as exc:
        msg = f'insertion {alias!r}: cannot resolve {entry!r} ({exc})'
        raise _EntryPointError(msg) from exc

    if not callable(target):
        msg = f'insertion {alias!r}: {entry!r} is not callable'
        raise _EntryPointError(msg)
    return target


def _import_entry_module(module_name: str, debug_file: Path) -> ModuleType:
    """Import the entry module; a leading dot resolves against the scratch dir.

    The scratch directory is prepended to ``sys.path`` and stays there for the
    run, so prototype modules can import siblings during rendering too. Stale
    same-name modules are dropped first, so iterating on a prototype within one
    process picks up new file content.
    """
    if not module_name.startswith('.'):
        return import_module(module_name)
    resolved = module_name[1:]
    scratch_dir = str(debug_file.parent)
    sys.modules.pop(resolved, None)
    if scratch_dir not in sys.path:
        sys.path.insert(0, scratch_dir)
    return import_module(resolved)


def _collect_zone_declarations(
    template: str,
    rendered: str,
    source_path: str,
) -> tuple[InsertZoneDeclaration, ...]:
    """Extract zone declarations the way the apply ferry does.

    Pre-render declarations come from the raw template; after-render ones from
    the rendered text, so loop-generated directives are found. Name-keyed with
    the after-render phase winning, mirroring the ferry merge order.
    """
    merged = {
        declaration.name: declaration
        for declaration in extract_insert_zone_declarations(
            template,
            DirectivePhase.PRE_RENDER.value,
            source_path,
        )
    }
    merged.update(
        {
            declaration.name: declaration
            for declaration in extract_insert_zone_declarations(
                rendered,
                DirectivePhase.AFTER_RENDER.value,
                source_path,
            )
        },
    )
    return tuple(merged.values())


def _run_insertion_stage(
    after_rendered: str,
    template: str,
    rendered: str,
    registry: dict[str, Callable[..., str]],
    debug_file: Path,
) -> tuple[str, list]:
    """Fill ``repolish:on`` blocks and insert zones; return text and diagnostics."""
    zones = _collect_zone_declarations(template, rendered, str(debug_file))
    result, _zone_blocks = render_insertions_text(
        after_rendered,
        registry,
        file_path=str(debug_file),
        zone_declarations=zones,
        zone_registry=registry,
    )
    return result.text, result.diagnostics
