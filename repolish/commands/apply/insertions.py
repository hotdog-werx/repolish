"""Apply insertion registries to non-owned files after file writes."""

from __future__ import annotations

import difflib
import json
from typing import TYPE_CHECKING

from hotlog import get_logger

from repolish.commands.apply.options import InsertionFileResult
from repolish.insertions import write_back, write_file

if TYPE_CHECKING:
    from pathlib import Path

    from repolish.providers import SessionBundle

logger = get_logger(__name__)


def apply_registered_insertions(
    providers: SessionBundle,
    base_dir: Path,
) -> dict[str, InsertionFileResult]:
    """Render provider-registered insertion blocks into target files in-place."""
    results: dict[str, InsertionFileResult] = {}
    reports_dir = base_dir / '.repolish' / '_' / 'insertions'
    reports_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, registry in providers.file_insertions.items():
        if rel_path in providers.paused_files:
            continue

        target = base_dir / rel_path
        if not target.exists() or target.is_dir():
            continue

        result = write_file(target, registry)
        if result.total_blocks == 0:
            continue

        report_file = reports_dir / f'insertions.{_report_slug(rel_path)}.json'
        source_provider = providers.insertion_sources.get(rel_path)
        report_file.write_text(
            json.dumps(
                {
                    'file': rel_path,
                    'source_provider': source_provider,
                    'total_blocks': result.total_blocks,
                    'failed_blocks': result.failed_blocks,
                    'functions': list(result.functions),
                    'diagnostics': [
                        {
                            'tag': diag.tag,
                            'message': diag.message,
                        }
                        for diag in result.diagnostics
                    ],
                },
                indent=2,
            ),
            encoding='utf-8',
        )

        results[rel_path] = InsertionFileResult(
            total_blocks=result.total_blocks,
            failed_blocks=result.failed_blocks,
            functions=result.functions,
            diagnostics=tuple(diag.message for diag in result.diagnostics),
            report_path=report_file.as_posix(),
        )

        if result.diagnostics:
            logger.warning(
                'file_insertions_render_failed',
                file=rel_path,
                diagnostics=[diag.message for diag in result.diagnostics],
                _display_level=1,
            )

    return results


def _report_slug(path: str) -> str:
    """Convert a destination path to a stable report filename slug."""
    return path.replace('/', '--')


def check_registered_insertions(
    providers: SessionBundle,
    base_dir: Path,
) -> list[tuple[str, str]]:
    """Return insertion drift diffs for check mode without mutating files."""
    diffs: list[tuple[str, str]] = []

    for rel_path, registry in providers.file_insertions.items():
        if rel_path in providers.paused_files:
            continue

        target = base_dir / rel_path
        if not target.exists() or target.is_dir():
            continue

        current = target.read_text(encoding='utf-8')
        rendered = write_back(current, registry).text
        if current == rendered:
            continue

        diff_text = ''.join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=rel_path,
                tofile=rel_path,
            ),
        )
        diffs.append((rel_path, diff_text))

    return diffs
