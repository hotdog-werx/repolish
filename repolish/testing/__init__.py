"""Testing utilities for repolish provider authors.

Provides :class:`ProviderTestBed` to exercise provider lifecycle hooks
(context creation, input exchange, file mappings, anchors, and template
rendering) without requiring a full CLI pipeline, git repo, or installed
wheels.

Typical usage::

    from repolish.testing import ProviderTestBed
    from my_provider.repolish.provider import MyProvider
    from my_provider.repolish.models import MyContext

    bed = ProviderTestBed(MyProvider, MyContext(flag=True))
    assert 'expected' in bed.render('template.jinja')
"""

from repolish.testing._context import make_context
from repolish.testing._snapshot import assert_snapshots
from repolish.testing._snapshot_filters import exclude_paths, include_paths
from repolish.testing._snapshot_runner import (
    SnapshotRunOptions,
    mock_provider_entry,
    run_snapshot_case,
)
from repolish.testing._testbed import ProviderTestBed

__all__ = [
    'ProviderTestBed',
    'SnapshotRunOptions',
    'assert_snapshots',
    'exclude_paths',
    'include_paths',
    'make_context',
    'mock_provider_entry',
    'run_snapshot_case',
]
