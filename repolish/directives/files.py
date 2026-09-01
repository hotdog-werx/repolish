"""File-level directive processing: the node interface for template/local pairs.

Everything in this module builds on the pure text API in :mod:`~repolish.directives.core`
and owns the file I/O concerns that pipeline code used to re-implement per
call site: UTF-8 reads with a binary/unreadable guard, phase application via
:func:`process_text`, and mode-preserving write-back.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from hotlog import get_logger

from repolish.directives.core import (
    PostPass,
    process_text,
)
from repolish.directives.phases import DirectivePhase
from repolish.directives.registry import FerriedItem, ferrying_families
from repolish.marker_kit import read_text_or_none, write_mode_preserved

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
class FileProcessResult:
    """Outcome of processing a single file pair.

    ``ferry`` carries what each ferrying family extracted from the raw
    template text, keyed by family name, with the pair's destination stamped
    on every item (:class:`~repolish.directives.registry.FerriedItem`).
    """

    content: str
    changed: bool
    ferry: dict[str, tuple[FerriedItem, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class PhaseResult:
    """Summary of :func:`run_phase` over a set of file pairs.

    ``ferry`` is the per-family union of every pair's ferry, in pair order.
    """

    changed: tuple[str, ...]
    skipped: tuple[str, ...]
    ferry: dict[str, tuple[FerriedItem, ...]] = field(default_factory=dict)


def _run_ferry_hooks(
    template_text: str,
    template_path: Path,
    local_path: Path | None,
    phase: DirectivePhase,
) -> dict[str, tuple[FerriedItem, ...]]:
    """Run every ferrying family's hook on the raw template text.

    Each item is stamped with the pair's destination — the local project
    file when the pair has one, else the staged file itself. Families whose
    hook yields nothing are omitted, so an empty dict means "nothing ferried".
    """
    families = ferrying_families()
    if not families:
        return {}
    dest = str(local_path) if local_path is not None else str(template_path)
    ferry: dict[str, tuple[FerriedItem, ...]] = {}
    for family in families:
        hook = family.ferry
        if hook is None:  # pragma: no cover -- ferrying_families() filters these
            continue
        payloads = hook(template_text, phase.value, str(template_path))
        if payloads:
            ferry[family.name] = tuple(FerriedItem(dest=dest, payload=payload) for payload in payloads)
    return ferry


def process_file(
    template_path: Path,
    local_path: Path | None = None,
    *,
    phase: DirectivePhase = DirectivePhase.PRE_RENDER,
    anchors: dict[str, str] | None = None,
    post_passes: Iterable[PostPass] | None = None,
) -> FileProcessResult | None:
    """Read *template_path* and apply the given phase against *local_path*.

    Pure with respect to the filesystem — the file is read but never written;
    persisting is the caller's choice (see :func:`write_if_changed`).

    Returns ``None`` when the template file is unreadable or not valid UTF-8
    (e.g. binary); the local file simply counts as absent when missing.
    """
    template_text = read_text_or_none(template_path)
    if template_text is None:
        logger.debug(
            'skipping_unreadable_file',
            template_file=str(template_path),
        )
        return None

    local_text = safe_file_read(local_path) if local_path is not None else ''
    content = process_text(
        template_text,
        local_text,
        anchors,
        phase=phase,
        source_path=str(template_path),
        post_passes=post_passes,
    )
    return FileProcessResult(
        content=content,
        changed=content != template_text,
        ferry=_run_ferry_hooks(template_text, template_path, local_path, phase),
    )


def write_if_changed(path: Path, result: FileProcessResult) -> bool:
    """Write *result.content* back to *path* when it differs, preserving mode.

    Returns True when the file was written.
    """
    if not result.changed:
        return False
    write_mode_preserved(path, result.content)
    return True


def run_phase(
    phase: DirectivePhase,
    pairs: Iterable[FilePair],
    *,
    anchors: dict[str, str] | None = None,
    post_passes: Iterable[PostPass] | None = None,
) -> PhaseResult:
    """Apply *phase* to every pair and write back files that changed.

    Pairing (which rendered file reconciles against which local file) is the
    caller's responsibility — it is pipeline-layout knowledge, not a
    directive concern.
    """
    logger.debug('running_phase', phase=phase.value)
    changed: list[str] = []
    skipped: list[str] = []
    ferry: dict[str, list[FerriedItem]] = {}
    for pair in pairs:
        result = process_file(
            pair.template_path,
            pair.local_path,
            phase=phase,
            anchors=anchors,
            post_passes=post_passes,
        )
        if result is None:
            skipped.append(str(pair.template_path))
            continue
        for family_name, items in result.ferry.items():
            ferry.setdefault(family_name, []).extend(items)
        if write_if_changed(pair.template_path, result):
            changed.append(str(pair.template_path))
    logger.debug(
        'phase_completed',
        phase=phase.value,
        changed=len(changed),
        skipped=len(skipped),
    )
    return PhaseResult(
        changed=tuple(changed),
        skipped=tuple(skipped),
        ferry={family: tuple(items) for family, items in ferry.items()},
    )
