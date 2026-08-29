"""Preprocessing utilities for repolish templates.

This package contains utilities for preprocessing template text around the
jinja render step — extracting directive patterns, applying phase-aware
replacements, and handling special repolish markers — plus file-level helpers
that run a phase over template/local file pairs.

Public layers:
    - Grammar: ``directives`` (one canonical pattern per directive family).
    - Text API: :func:`preprocess_text`, :func:`extract_patterns`,
      :func:`strip_directives` — pure transforms, no I/O.
    - File API: :func:`preprocess_file`, :func:`write_if_changed`,
      :func:`run_phase`, :func:`safe_file_read` — the file node.

Boundary rule: this package must not statically import any other ``repolish.*``
module (only directives-internal modules); orchestrators inject extras such as
insertion-marker adoption via ``post_passes``.
"""

from repolish.preprocessors.anchors import replace_tags_in_content
from repolish.preprocessors.core import (
    Patterns,
    PostPass,
    extract_patterns,
    preprocess_text,
    replace_text,
    safe_file_read,
    strip_directives,
)
from repolish.preprocessors.directive_phase import (
    PreprocessPhase,
    split_directive_tag,
    warn_invalid_phase_suffix,
)
from repolish.preprocessors.files import (
    FilePair,
    FilePreprocessResult,
    PhaseResult,
    preprocess_file,
    run_phase,
    write_if_changed,
)
from repolish.preprocessors.keep import apply_keep_replacements
from repolish.preprocessors.multiregex import apply_multiregex_replacements
from repolish.preprocessors.regex import apply_regex_replacements

__all__ = [
    'FilePair',
    'FilePreprocessResult',
    'Patterns',
    'PhaseResult',
    'PostPass',
    'PreprocessPhase',
    'apply_keep_replacements',
    'apply_multiregex_replacements',
    'apply_regex_replacements',
    'extract_patterns',
    'preprocess_file',
    'preprocess_text',
    'replace_tags_in_content',
    'replace_text',
    'run_phase',
    'safe_file_read',
    'split_directive_tag',
    'strip_directives',
    'warn_invalid_phase_suffix',
    'write_if_changed',
]
