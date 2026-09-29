"""The single authority on file-mode semantics.

``FileMode`` declares a destination's disposition;
:class:`~repolish.filemodes.rules.ModeRules` turns the session's
declarations into the decisions every writer and checker asks by name, and
:func:`~repolish.filemodes.rules.fold_mapping` is the one table that maps
a mode to its destination-set claim during accumulation. Consumers never
re-derive these rules; the regression fixed alongside this package (a
writer path missing the create-only rule) is the reason they no longer can.
"""

from repolish.filemodes.rules import (
    MATERIALIZED_MODES,
    FileMode,
    ModeRules,
    ModeSet,
    fold_mapping,
    posix_dests,
)

__all__ = [
    'MATERIALIZED_MODES',
    'FileMode',
    'ModeRules',
    'ModeSet',
    'fold_mapping',
    'posix_dests',
]
