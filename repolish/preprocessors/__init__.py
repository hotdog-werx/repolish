"""Compatibility shim for the old ``repolish.preprocessors`` import path.

The package was renamed to :mod:`repolish.directives` (the name encodes the
artifacts it processes, not the phase timing). The public names below keep
working; new code should import from ``repolish.directives`` and use
``process_text``/``process_file``/``DirectivePhase``/``FileProcessResult``.

Only the import path and renames are supported here — internal submodules
(``keep``, ``registry``, ...) live solely under ``repolish.directives``.
"""

from repolish.directives import (
    DirectivePhase,
    FilePair,
    FileProcessResult,
    Patterns,
    PhaseResult,
    PostPass,
    extract_patterns,
    process_file,
    process_text,
    run_phase,
    strip_directives,
    write_if_changed,
)

PreprocessPhase = DirectivePhase
FilePreprocessResult = FileProcessResult
preprocess_text = process_text
preprocess_file = process_file

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
