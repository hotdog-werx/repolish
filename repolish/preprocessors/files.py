"""File-level preprocessing: the node interface for template/local pairs.

Everything in this module builds on the pure text API in :mod:`~repolish.preprocessors.core`
and owns the file I/O concerns that pipeline code used to re-implement per
call site: UTF-8 reads with a binary/unreadable guard, phase application via
:func:`preprocess_text`, and mode-preserving write-back.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from hotlog import get_logger

from repolish.preprocessors.core import (
    PostPass,
    preprocess_text,
)
from repolish.preprocessors.directive_phase import PreprocessPhase

logger = get_logger(__name__)


def safe_file_read(file_path: Path) -> str:
    """Safely reads the content of a file if it exists.

    Args:
        file_path: Path to the file to read.

    Returns:
        The content of the file, or an empty string if the file does not exist.
    """
    if file_path.exists() and file_path.is_file():
        return file_path.read_text(encoding='utf-8')
    return ''


@dataclass(frozen=True)
class FilePair:
    """A template/rendered file and the local file it reconciles against.

    ``local_path`` may be ``None`` (or point at a nonexistent file), in which
    case the local side is treated as empty — the template keeps its defaults.
    """

    template_path: Path
    local_path: Path | None = None


@dataclass(frozen=True)
class FilePreprocessResult:
    """Outcome of preprocessing a single file pair."""

    content: str
    changed: bool


@dataclass(frozen=True)
class PhaseResult:
    """Summary of :func:`run_phase` over a set of file pairs."""

    changed: tuple[str, ...]
    skipped: tuple[str, ...]


def preprocess_file(
    template_path: Path,
    local_path: Path | None = None,
    *,
    phase: PreprocessPhase = PreprocessPhase.PRE_RENDER,
    anchors: dict[str, str] | None = None,
    post_passes: Iterable[PostPass] | None = None,
) -> FilePreprocessResult | None:
    """Read *template_path* and apply the given phase against *local_path*.

    Pure with respect to the filesystem — the file is read but never written;
    persisting is the caller's choice (see :func:`write_if_changed`).

    Returns ``None`` when the template file is unreadable or not valid UTF-8
    (e.g. binary); the local file simply counts as absent when missing.
    """
    try:
        template_text = template_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug(
            'skipping_unreadable_file',
            template_file=str(template_path),
            error=str(exc),
        )
        return None

    local_text = safe_file_read(local_path) if local_path is not None else ''
    content = preprocess_text(
        template_text,
        local_text,
        anchors,
        phase=phase,
        source_path=str(template_path),
        post_passes=post_passes,
    )
    return FilePreprocessResult(content=content, changed=content != template_text)


def write_if_changed(path: Path, result: FilePreprocessResult) -> bool:
    """Write *result.content* back to *path* when it differs, preserving mode.

    Returns True when the file was written.
    """
    if not result.changed:
        return False
    mode = path.stat().st_mode
    path.write_text(result.content, encoding='utf-8')
    path.chmod(mode)
    return True


def run_phase(
    phase: PreprocessPhase,
    pairs: Iterable[FilePair],
    *,
    anchors: dict[str, str] | None = None,
    post_passes: Iterable[PostPass] | None = None,
) -> PhaseResult:
    """Apply *phase* to every pair and write back files that changed.

    Pairing (which rendered file reconciles against which local file) is the
    caller's responsibility — it is pipeline-layout knowledge, not a
    preprocessor concern.
    """
    logger.debug('running_phase', phase=phase.value)
    changed: list[str] = []
    skipped: list[str] = []
    for pair in pairs:
        result = preprocess_file(
            pair.template_path,
            pair.local_path,
            phase=phase,
            anchors=anchors,
            post_passes=post_passes,
        )
        if result is None:
            skipped.append(str(pair.template_path))
            continue
        if write_if_changed(pair.template_path, result):
            changed.append(str(pair.template_path))
    logger.debug('phase_completed', phase=phase.value, changed=len(changed), skipped=len(skipped))
    return PhaseResult(changed=tuple(changed), skipped=tuple(skipped))
