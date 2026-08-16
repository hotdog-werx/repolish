"""Write replacement text back into source documents using insertion blocks."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from repolish.insertions.models import CommentStyle, InsertionBlock
from repolish.insertions.parser import parse_text

Renderer = Callable[[InsertionBlock], str]
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
    leading = body[: len(body) - len(body.lstrip())]
    trailing = body[len(body.rstrip()) :]
    return leading, trailing


def _call_registered_renderer(
    registry: RenderRegistry,
    block: InsertionBlock,
) -> str:
    """Resolve and call a function from a registry using the block metadata."""
    function_name = block.function
    fn = registry.get(function_name)
    if fn is None and ':' in function_name:
        fn = registry.get(function_name.rsplit(':', 1)[1])
    if fn is None:
        msg = f'No renderer registered for function {function_name!r}.'
        raise KeyError(msg)

    params = tuple(inspect.signature(fn).parameters.values())
    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    positional = [
        p
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]

    if positional and len(positional) == 1 and not has_varargs:
        return fn(block)
    if block.args:
        return fn(*block.args)
    return fn()


def _render_block(
    render: Renderer | RenderRegistry | None,
    block: InsertionBlock,
) -> str:
    """Render a block using either a direct callback or a named function registry."""
    if render is None:
        return block.body
    if isinstance(render, Mapping):
        return _call_registered_renderer(render, block)
    return render(block)


def write_back(
    text: str,
    render: Renderer | RenderRegistry | None = None,
    *,
    comment_styles: Iterable[CommentStyle | str] | None = None,
) -> WriteBackResult:
    """Replace each parsed insertion block body while preserving the markers.

    The renderer receives the full insertion metadata so repeated tags are handled
    naturally and each block can decide what content should be inserted.
    """
    parsed = parse_text(text, comment_styles=comment_styles)
    if not parsed.blocks:
        return WriteBackResult(text=text)

    result: list[str] = []
    diagnostics: list[WriteDiagnostic] = []
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
        result.append(trailing)
        result.append(text[block.body_end : block.end])
        cursor = block.end

    result.append(text[cursor:])
    return WriteBackResult(
        text=''.join(result),
        diagnostics=diagnostics,
        total_blocks=len(parsed.blocks),
        failed_blocks=failed_blocks,
        functions=tuple(functions),
    )


def write_file(
    path: str | Path,
    render: Renderer | RenderRegistry | None = None,
    *,
    comment_styles: Iterable[CommentStyle | str] | None = None,
) -> WriteBackResult:
    """Render insertion blocks in a file and write the updated content back."""
    file_path = Path(path)
    original = file_path.read_text(encoding='utf-8')
    updated = write_back(
        original,
        render,
        comment_styles=comment_styles,
    )
    file_path.write_text(updated.text, encoding='utf-8')
    return updated
