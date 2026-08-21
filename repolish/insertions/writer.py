"""Write replacement text back into source documents using insertion blocks."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from repolish.insertions.models import CommentStyle, InsertionBlock
from repolish.insertions.parser import parse_text

Renderer = Callable[..., str]
RenderRegistry = Mapping[str, Callable[..., str]]


@dataclass(frozen=True)
class WriteDiagnostic:
    """A structured summary of a block render failure."""

    tag: str
    message: str
    exception: Exception | None = None


@dataclass(frozen=True)
class WriteBackResult:
    """The final rewritten document and any rendering diagnostics."""

    text: str
    diagnostics: list[WriteDiagnostic] = field(default_factory=list)
    total_blocks: int = 0
    failed_blocks: int = 0
    functions: tuple[str, ...] = field(default_factory=tuple)


def _preserve_block_whitespace(body: str) -> tuple[str, str]:
    """Return the body margins that should be preserved around replacement text."""
    lines = body.splitlines()
    leading = f'{lines[0]}\n'
    last_line = lines[-1] if len(lines) > 1 else ''
    trailing = last_line[len(last_line.rstrip()) :]
    return leading, trailing


def _call_registered_renderer(
    registry: RenderRegistry,
    block: InsertionBlock,
) -> str:
    """Resolve and call a function from a registry using the block metadata.

    Function signatures are inspected and called appropriately:
    - Single InsertionBlock param (positional): pass the full block
    - Keyword-only `block: InsertionBlock`: inject the block
    - VAR_POSITIONAL (*args): pass all marker args directly
    - Positional params: filled from marker args, uses defaults if available
    """
    function_name = block.function
    fn = registry.get(function_name)
    if fn is None and ':' in function_name:
        fn = registry.get(function_name.rsplit(':', 1)[1])
    if fn is None:
        msg = f'No renderer registered for function {function_name!r}.'
        raise KeyError(msg)

    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    positional_params = _get_positional_params(params)

    # Single InsertionBlock param (positional, used by wrapper functions)
    if _is_single_block_param(positional_params, has_varargs=has_varargs):
        return fn(block)

    # Varargs - pass all marker args directly
    if has_varargs:
        return fn(*block.args)

    # Check for keyword-only context injection
    call_kwargs = _build_call_kwargs(params, block)
    if call_kwargs is not None:
        return fn(**call_kwargs)

    # Build positional args from marker args, use defaults if missing
    call_args = _build_call_args(positional_params, block.args, function_name)
    return fn(*call_args)


def _build_call_kwargs(
    params: list[inspect.Parameter],
    block: InsertionBlock,
) -> dict[str, object] | None:
    """Build kwargs for keyword-only context params. Returns None if no kwargs needed."""
    call_kwargs: dict[str, object] = {}
    for p in params:
        if p.kind != inspect.Parameter.KEYWORD_ONLY:
            continue
        if _is_insertion_block_annotation(p.annotation):
            call_kwargs['block'] = block

    return call_kwargs if call_kwargs else None


def _get_positional_params(
    params: list[inspect.Parameter],
) -> list[inspect.Parameter]:
    """Extract positional-only and positional-or-keyword parameters."""
    return [
        p
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]


def _is_single_block_param(
    positional_params: list[inspect.Parameter],
    *,
    has_varargs: bool,
) -> bool:
    """Check if signature has a single InsertionBlock parameter."""
    return (
        len(positional_params) == 1
        and not has_varargs
        and _is_insertion_block_annotation(
            positional_params[0].annotation,
        )
    )


def _build_call_args(
    positional_params: list[inspect.Parameter],
    marker_args: tuple[str, ...],
    function_name: str,
) -> list[Any]:
    """Build call args from marker args, using defaults for missing values."""
    call_args: list[Any] = []
    for i, param in enumerate(positional_params):
        if i < len(marker_args):
            call_args.append(marker_args[i])
        elif param.default is not inspect.Parameter.empty:
            call_args.append(param.default)
        else:
            msg = (
                f'Function {function_name!r} requires {len(positional_params)} positional args, '
                f'but marker provided only {len(marker_args)}. '
                f'Missing: {param.name!r}'
            )
            raise TypeError(msg)
    return call_args


def _is_insertion_block_annotation(annotation: object) -> bool:
    """Check if an annotation refers to InsertionBlock."""
    if annotation is InsertionBlock:
        return True
    return bool(isinstance(annotation, str) and annotation == 'InsertionBlock')


def _render_block(
    render: Renderer | RenderRegistry | None,
    block: InsertionBlock,
) -> str:
    """Render a block using either a direct callback or a named function registry."""
    if isinstance(render, Mapping):
        return _call_registered_renderer(render, block)
    return render(block) if render else block.body


def write_back(
    text: str,
    render: Renderer | RenderRegistry | None = None,
    *,
    comment_styles: Iterable[CommentStyle | str] | None = None,
    file_path: str = '',
) -> WriteBackResult:
    """Replace each parsed insertion block body while preserving the markers.

    The renderer receives the full insertion metadata so repeated tags are handled
    naturally and each block can decide what content should be inserted.

    Parse diagnostics (malformed markers, unclosed blocks) are passed through
    so callers can see both parse and render issues.

    Args:
        text: The file content to process.
        render: Renderer function or registry for rendering block content.
        comment_styles: The comment styles to recognize.
        file_path: The path of the file being processed (stored in each InsertionBlock).
    """
    parsed = parse_text(
        text,
        comment_styles=comment_styles,
        file_path=file_path,
    )

    # Convert parse diagnostics to write diagnostics
    diagnostics: list[WriteDiagnostic] = [
        WriteDiagnostic(tag='<parse>', message=d.message) for d in parsed.diagnostics
    ]

    if not parsed.blocks:
        return WriteBackResult(
            text=text,
            diagnostics=diagnostics,
            total_blocks=0,
            failed_blocks=len(diagnostics),
            functions=(),
        )

    result: list[str] = []
    functions: list[str] = []
    failed_blocks = 0
    cursor = 0
    for block in parsed.blocks:
        functions.append(block.function)
        result.append(text[cursor : block.start])
        result.append(text[block.start : block.body_start])
        leading, trailing = _preserve_block_whitespace(
            text[block.body_start : block.body_end],
        )
        result.append(leading)
        try:
            result.append(_render_block(render, block))
        except Exception as exc:  # noqa: BLE001 - record renderer failures for later diagnostics output
            failed_blocks += 1
            diagnostics.append(
                WriteDiagnostic(
                    tag=block.tag,
                    message=str(exc),
                    exception=exc,
                ),
            )
            result.append('')
        if result[-1] and not result[-1].endswith('\n'):
            # no trailing newline in the rendered content, so preserve the original trailing whitespace
            result.append('\n')
        result.append(trailing)
        result.append(text[block.body_end : block.end])
        cursor = block.end

    result.append(text[cursor:])
    return WriteBackResult(
        text=''.join(result),
        diagnostics=diagnostics,
        total_blocks=len(parsed.blocks),
        failed_blocks=failed_blocks + len(parsed.diagnostics),
        functions=tuple(functions),
    )
