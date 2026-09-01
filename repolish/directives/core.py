"""Core directive-processing utilities for templates.

The pure text layer of the directives package: ``extract_patterns``
discovers directive patterns and ``process_text`` applies the registered
directive families (see :mod:`~repolish.directives.registry`) around the
tag-block replacement pass. No file I/O lives here — that is ``files.py``.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from hotlog import get_logger

from repolish.directives.anchors import replace_tags_in_content
from repolish.directives.definitions import TAG_BLOCK_RE, warn_legacy_dash_directives
from repolish.directives.keep import KeepPatterns
from repolish.directives.multiregex import MultiregexPatterns
from repolish.directives.phases import DirectivePhase
from repolish.directives.registry import FAMILIES

logger = get_logger(__name__)


class PostPass(Protocol):
    """A text transform applied after the built-in directive passes.

    Lets orchestrators (e.g. the apply session) extend a phase with extra
    reconciliation — such as insertion-marker adoption — without the
    preprocessors package importing those features itself.
    """

    def __call__(
        self,
        content: str,
        local_content: str,
        *,
        source_path: str | None = None,
    ) -> str:
        """Return *content* after reconciling it with *local_content*."""
        ...


@dataclass
class Patterns:
    """Container for extracted patterns from content.

    Family payloads live in ``by_family``, keyed by the family names from
    :data:`~repolish.directives.registry.FAMILIES``. The flat per-family
    accessors below are read-only compatibility views over those payloads.
    """

    tag_blocks: dict[str, str]
    by_family: dict[str, object] = field(default_factory=dict)

    @property
    def _keep(self) -> KeepPatterns | None:
        value = self.by_family.get('keep')
        return value if isinstance(value, KeepPatterns) else None

    @property
    def keep_blocks(self) -> dict[str, tuple[str, str | None, str | None]]:
        """Keep-block bounds as ``(start, end, end_regex)`` tuples."""
        keep = self._keep
        if keep is None:
            return {}
        return {name: (spec.start, spec.end, spec.end_regex) for name, spec in keep.blocks.items()}

    @property
    def keep_rest(self) -> dict[str, str]:
        """Keep-rest markers keyed by directive name."""
        keep = self._keep
        if keep is None:
            return {}
        return {name: spec.marker for name, spec in keep.rest.items()}

    @property
    def keep_header(self) -> dict[str, str]:
        """Keep-header markers keyed by directive name."""
        keep = self._keep
        if keep is None:
            return {}
        return {name: spec.marker for name, spec in keep.header.items()}

    @property
    def regexes(self) -> dict[str, str]:
        """Regex directives keyed by directive name."""
        value = self.by_family.get('regex')
        return value if isinstance(value, dict) else {}

    @property
    def _multiregex(self) -> MultiregexPatterns | None:
        value = self.by_family.get('multiregex')
        return value if isinstance(value, MultiregexPatterns) else None

    @property
    def multiregex_blocks(self) -> dict[str, str]:
        """Multiregex block patterns keyed by directive name."""
        multiregex = self._multiregex
        return dict(multiregex.blocks) if multiregex is not None else {}

    @property
    def multiregexes(self) -> dict[str, str]:
        """Multiregex value patterns keyed by directive name."""
        multiregex = self._multiregex
        return dict(multiregex.regexes) if multiregex is not None else {}


def _extract_tag_blocks(content: str) -> dict[str, str]:
    """Extract repolish-start/end blocks preserving only inner content."""
    raw_tag_blocks = dict(TAG_BLOCK_RE.findall(content))
    return {key: value.strip('\n') for key, value in raw_tag_blocks.items()}


def extract_patterns(
    content: str,
    *,
    phase: DirectivePhase = DirectivePhase.PRE_RENDER,
    source_path: str | None = None,
) -> Patterns:
    """Extracts text blocks and regex patterns from the given content.

    Args:
        content: The input string containing text blocks and regex patterns.
        phase: Directive phase to extract (`pre-render` or `after-render`).
        source_path: Optional template path used for contextual warning logs.

    Returns:
        A Patterns object containing extracted tag blocks and family payloads.
    """
    if phase == DirectivePhase.PRE_RENDER:
        warn_legacy_dash_directives(content, source_path=source_path)

    selected_phase = phase.value

    tag_blocks = _extract_tag_blocks(content)
    by_family = {family.name: family.extract(content, selected_phase, source_path) for family in FAMILIES}

    logger.debug(
        'extracted_patterns',
        phase=selected_phase,
        tag_blocks=[str(k) for k in tag_blocks],
        families=list(by_family),
    )

    return Patterns(tag_blocks=tag_blocks, by_family=by_family)


def process_text(  # noqa: PLR0913 - canonical entry point, params are the public contract
    template_content: str,
    local_content: str,
    anchors_dictionary: dict[str, str] | None = None,
    *,
    phase: DirectivePhase = DirectivePhase.PRE_RENDER,
    source_path: str | None = None,
    post_passes: Iterable[PostPass] | None = None,
) -> str:
    """Replaces tag blocks and regex patterns in the template content.

    This is the canonical pure text-transform entry point of the preprocessors
    package: template text in, processed text out, with no file I/O.

    Args:
        template_content: The content of the template file.
        local_content: The content of the local file to extract patterns from.
        anchors_dictionary: Optional dictionary of anchor replacements provided by
            configuration (maps tag name -> replacement text). If provided, values
            in this dict will be used to replace corresponding `## repolish-start[...]` blocks
            in the template. If not provided, the template's own block contents are
            preserved.
        phase: Directive phase to apply (`pre-render` or `after-render`).
        source_path: Optional template path used for contextual warning logs.
        post_passes: Extra transforms applied after the built-in directive
            passes, each receiving ``(content, local_content, *, source_path)``.
            When ``None``, the legacy default applies: the ``after-render``
            phase additionally adopts local insertion markers. Pass an explicit
            iterable (possibly empty) to control the passes yourself.

    Returns:
        The modified template content with replaced tag blocks and regex patterns.
    """
    selected_phase = phase.value

    logger.debug(
        'starting_text_replacement',
        has_anchors=anchors_dictionary is not None,
        phase=selected_phase,
    )

    patterns = extract_patterns(
        template_content,
        phase=phase,
        source_path=source_path,
    )

    # Build the replacement mapping for tag blocks. If an anchors dictionary is
    # provided, use its values to replace the corresponding tag blocks. Otherwise
    # fall back to the template's own block content (i.e. leave defaults).
    content = template_content
    tags_to_replace: dict[str, str] = {}
    if selected_phase == DirectivePhase.PRE_RENDER.value:
        for tag, default_value in patterns.tag_blocks.items():
            if anchors_dictionary and tag in anchors_dictionary:
                tags_to_replace[tag] = anchors_dictionary[tag]
            else:
                tags_to_replace[tag] = default_value
        content = replace_tags_in_content(template_content, tags_to_replace)

    for family in FAMILIES:
        content = family.apply(
            content,
            patterns.by_family[family.name],
            local_content,
            selected_phase,
            source_path,
        )

    result = _run_post_passes(
        content,
        local_content,
        selected_phase=selected_phase,
        source_path=source_path,
        post_passes=post_passes,
    )
    logger.debug(
        'text_replacement_completed',
        tag_blocks_replaced=len(tags_to_replace),
        families_applied=[family.name for family in FAMILIES],
    )
    return result


def _run_post_passes(
    content: str,
    local_content: str,
    *,
    selected_phase: str,
    source_path: str | None,
    post_passes: Iterable[PostPass] | None,
) -> str:
    """Apply caller-supplied post passes, or the legacy after-render default."""
    if post_passes is None and selected_phase == DirectivePhase.AFTER_RENDER.value:
        # Legacy default: preserve developer-chosen insertion function/args
        # from the local file. Runs only after render so loop-generated markers
        # are fully concrete. Imported lazily so the directives package has
        # no static dependency on repolish.insertions — orchestrators should
        # pass post_passes explicitly instead (see commands/apply/session.py).
        from repolish.insertions.adoption import (  # noqa: PLC0415 - legacy default, keeps insertions out of the static dependency graph
            adopt_local_insertion_markers,
        )

        return adopt_local_insertion_markers(
            content,
            local_content,
            source_path=source_path,
        )
    if post_passes:
        for post_pass in post_passes:
            content = post_pass(
                content,
                local_content,
                source_path=source_path,
            )
    return content


def strip_directives(
    content: str,
    *,
    phase: DirectivePhase = DirectivePhase.PRE_RENDER,
    source_path: str | None = None,
) -> str:
    """Strip directive lines and resolve defaults against an empty local file.

    Intended for tooling (e.g. lint) that needs directive-free template text
    before further parsing. Tag blocks keep their template defaults and keep
    regions resolve from the template itself, since there is no local content
    to extract overrides from.
    """
    return process_text(content, '', phase=phase, source_path=source_path)
