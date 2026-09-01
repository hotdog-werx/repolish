"""Directive processing for repolish templates.

``repolish-*`` markers in template files are *directives*: they tell repolish
what to preserve, adopt, or default when reconciling rendered output with the
developer's files. This package owns their grammar and execution across both
phases — ``pre-render`` (on staged templates, before Jinja) and
``after-render`` (on rendered output) — plus file-level helpers that run a
phase over template/local file pairs.

Public layers:
    - Text API: :func:`process_text`, :func:`extract_patterns`,
      :func:`strip_directives` — pure transforms, no I/O.
    - File API: :func:`process_file`, :func:`write_if_changed`,
      :func:`run_phase` — the file node, plus their pairing/result types.

Only the names listed in ``__all__`` are public. Family implementations
(``anchors``, ``keep``, ``regex``, ``multiregex``) and the grammar internals
(``definitions``, ``phases``, ``tag_names``) are private to the package. The
extension point for new directive families is ``registry.py``: one family
module plus one :class:`~repolish.directives.registry.DirectiveFamily` entry,
and nothing outside ``repolish.directives`` changes.

Boundary rule: this package must not statically import any other ``repolish.*``
module except ``repolish.marker_kit`` — the shared internal leaf whose span,
pairing, splice, and file I/O mechanics this package and
``repolish.insertions`` both drive. Orchestrators inject extras such as
insertion-marker adoption via ``post_passes``.
"""

from repolish.directives.core import (
    Patterns,
    PostPass,
    extract_patterns,
    process_text,
    strip_directives,
)
from repolish.directives.files import (
    FilePair,
    FileProcessResult,
    PhaseResult,
    process_file,
    run_phase,
    write_if_changed,
)
from repolish.directives.phases import DirectivePhase
from repolish.directives.registry import FerriedItem

__all__ = [
    'DirectivePhase',
    'FerriedItem',
    'FilePair',
    'FileProcessResult',
    'Patterns',
    'PhaseResult',
    'PostPass',
    'extract_patterns',
    'process_file',
    'process_text',
    'run_phase',
    'strip_directives',
    'write_if_changed',
]
