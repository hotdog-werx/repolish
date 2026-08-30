"""Preprocessing utilities for repolish templates.

This package contains utilities for preprocessing template text around the
jinja render step — extracting directive patterns, applying phase-aware
replacements, and handling special repolish markers — plus file-level helpers
that run a phase over template/local file pairs.

Public layers:
    - Text API: :func:`preprocess_text`, :func:`extract_patterns`,
      :func:`strip_directives` — pure transforms, no I/O.
    - File API: :func:`preprocess_file`, :func:`write_if_changed`,
      :func:`run_phase` — the file node, plus their pairing/result types.

Only the names listed in ``__all__`` are public. Family implementations
(``anchors``, ``keep``, ``regex``, ``multiregex``) and the grammar internals
(``directives``, ``directive_phase``, ``tag_names``) are private to the
package. The extension point for new preprocessor families is
``registry.py``: one family module plus one
:class:`~repolish.preprocessors.registry.DirectiveFamily` entry, and nothing
outside ``repolish.preprocessors`` changes.

Boundary rule: this package must not statically import any other ``repolish.*``
module except ``repolish.marker_kit`` — the shared internal leaf whose span,
pairing, splice, and file I/O mechanics this package and
``repolish.insertions`` both drive. Orchestrators inject extras such as
insertion-marker adoption via ``post_passes``.
"""

from repolish.preprocessors.core import (
    Patterns,
    PostPass,
    extract_patterns,
    preprocess_text,
    strip_directives,
)
from repolish.preprocessors.directive_phase import PreprocessPhase
from repolish.preprocessors.files import (
    FilePair,
    FilePreprocessResult,
    PhaseResult,
    preprocess_file,
    run_phase,
    write_if_changed,
)

__all__ = [
    'FilePair',
    'FilePreprocessResult',
    'Patterns',
    'PhaseResult',
    'PostPass',
    'PreprocessPhase',
    'extract_patterns',
    'preprocess_file',
    'preprocess_text',
    'run_phase',
    'strip_directives',
    'write_if_changed',
]
