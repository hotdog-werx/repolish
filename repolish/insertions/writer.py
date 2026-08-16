"""Write replacement text back into source documents using insertion blocks."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from repolish.insertions.models import CommentStyle, InsertionBlock
from repolish.insertions.parser import parse_text

Renderer = Callable[[InsertionBlock], str]


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


def _preserve_block_whitespace(body: str) -> tuple[str, str]:
    """Return the body margins that should be preserved around replacement text."""
    leading = body[: len(body) - len(body.lstrip())]
    trailing = body[len(body.rstrip()) :]
    return leading, trailing


def write_back(
    text: str,
    render: Renderer | None = None,
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

    renderer = render or (lambda block: block.body)
    result: list[str] = []
    diagnostics: list[WriteDiagnostic] = []
    cursor = 0
    for block in parsed.blocks:
        result.append(text[cursor : block.start])
        result.append(text[block.start : block.body_start])
        leading, trailing = _preserve_block_whitespace(
            text[block.body_start : block.body_end],
        )
        result.append(leading)
        try:
            result.append(renderer(block))
        except Exception as exc:  # noqa: BLE001 - record renderer failures for later diagnostics output
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
    return WriteBackResult(text=''.join(result), diagnostics=diagnostics)


def write_file(
    path: str | Path,
    render: Renderer | None = None,
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
