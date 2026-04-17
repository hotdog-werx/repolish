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
from repolish.testing._testbed import ProviderTestBed

__all__ = [
    'ProviderTestBed',
    'assert_snapshots',
    'make_context',
]
