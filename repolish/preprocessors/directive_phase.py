"""Shared directive phase parsing and warning utilities."""

from enum import StrEnum

from hotlog import get_logger

logger = get_logger(__name__)


class PreprocessPhase(StrEnum):
    """Supported preprocessing phases."""

    PRE_RENDER = 'pre-render'
    AFTER_RENDER = 'after-render'


SUPPORTED_PHASES = {phase.value for phase in PreprocessPhase}


def split_directive_tag(
    raw_tag: str,
    *,
    source_path: str | None = None,
) -> tuple[str, str]:
    """Split directive tag into `(name, phase)` and warn/fallback on bad suffix."""
    if '|' not in raw_tag:
        return raw_tag, 'pre-render'

    name, maybe_phase = raw_tag.rsplit('|', 1)
    if maybe_phase in SUPPORTED_PHASES and name:
        return name, maybe_phase

    warn_invalid_phase_suffix(raw_tag, source_path=source_path)
    # Invalid suffix falls back to pre-render semantics by directive name.
    return (name or raw_tag), 'pre-render'


def warn_invalid_phase_suffix(
    raw_tag: str,
    *,
    source_path: str | None = None,
) -> None:
    """Warn for invalid directive phase suffixes with optional source context."""
    _, phase_suffix = raw_tag.rsplit('|', 1)

    logger.warning(
        'directive_invalid_phase_suffix',
        tag=raw_tag,
        phase_suffix=phase_suffix,
        allowed_phase_suffixes=['pre-render', 'after-render'],
        fallback_phase='pre-render',
        source_path=source_path,
    )
