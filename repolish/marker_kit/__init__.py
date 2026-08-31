"""Shared marker-driving machinery for repolish's file-level features.

Internal leaf package: it is the one cross-package dependency allowed inside
``repolish.directives`` and ``repolish.insertions``, and it itself imports
nothing from other ``repolish.*`` modules. Both feature packages implement the
same driver anatomy — scan text into regions, pair template regions against
local ones, splice results back — so the mechanics live here once:

- :mod:`~repolish.marker_kit.spans` — bounded marker regions
  (``start ... end``/``end-regex``) over line lists.
- :mod:`~repolish.marker_kit.pairing` — tag/occurrence-order pairing between
  two versions of a file, plus progressive occurrence tracking.
- :mod:`~repolish.marker_kit.splice` — offset-safe span replacement.
- :mod:`~repolish.marker_kit.fileio` — guarded UTF-8 reads and
  mode-preserving writes.

Nothing here knows about repolish directive grammar, insertion functions, or
pipelines; feature packages keep their own grammars and semantics.
"""

from repolish.marker_kit.fileio import read_text_or_none, write_mode_preserved
from repolish.marker_kit.pairing import (
    OccurrenceTracker,
    pair_in_occurrence_order,
)
from repolish.marker_kit.spans import (
    RegionBoundary,
    find_all_bounded_regions,
    find_bounded_region,
    find_bounded_regions_in_range,
    find_first_line_index,
    occurrence_key,
)
from repolish.marker_kit.splice import apply_splices

__all__ = [
    'OccurrenceTracker',
    'RegionBoundary',
    'apply_splices',
    'find_all_bounded_regions',
    'find_bounded_region',
    'find_bounded_regions_in_range',
    'find_first_line_index',
    'occurrence_key',
    'pair_in_occurrence_order',
    'read_text_or_none',
    'write_mode_preserved',
]
