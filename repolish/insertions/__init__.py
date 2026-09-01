"""Insertion block parsing and application for repolish-managed file slots."""

from repolish.insertions.disabled import (
    DisabledInsertionEntry,
    collect_disabled_entries,
    disabled_reason_for_block,
    resolve_renderer_for_function,
)
from repolish.insertions.files import (
    FileInsertionOutcome,
    apply_insertions_file,
    render_insertions_file,
)
from repolish.insertions.models import (
    BlockContext,
    CommentStyle,
    InsertionBlock,
    ParsedInsertions,
)
from repolish.insertions.parser import parse_text
from repolish.insertions.provider_resolution import (
    is_provider_owner,
    resolve_provider_function_name,
)
from repolish.insertions.reports import (
    DisabledDiagnosticEntry,
    ErrorDiagnosticEntry,
    InsertionReport,
)
from repolish.insertions.type_utils import (
    is_block_context_annotation,
    is_insertion_block_annotation,
)
from repolish.insertions.writer import (
    Renderer,
    WriteBackResult,
    WriteDiagnostic,
    write_back,
)

__all__ = [
    'BlockContext',
    'CommentStyle',
    'DisabledDiagnosticEntry',
    'DisabledInsertionEntry',
    'ErrorDiagnosticEntry',
    'FileInsertionOutcome',
    'InsertionBlock',
    'InsertionReport',
    'ParsedInsertions',
    'Renderer',
    'WriteBackResult',
    'WriteDiagnostic',
    'apply_insertions_file',
    'collect_disabled_entries',
    'disabled_reason_for_block',
    'is_block_context_annotation',
    'is_insertion_block_annotation',
    'is_provider_owner',
    'parse_text',
    'render_insertions_file',
    'resolve_provider_function_name',
    'resolve_renderer_for_function',
    'write_back',
]
