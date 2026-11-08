"""The durable link-creation utility.

Everything a project needs to link packaged resources into a working tree:
:func:`~repolish.links.symlinks.link_resources` and friends materialise the
chain real symlinks, Windows junction directories, plain copies, in that
order — whatever the platform allows. The ``resource_linker`` decorators
turn that core into a ready-made linking CLI for any library. This package
is deliberately self-contained so it survives on its own: repolish's
registration engine (:mod:`repolish.linker`) consumes it, and third-party
projects can too, without pulling in any provider machinery.
"""

from repolish.links.decorator import (
    resource_linker,
    resource_linker_cli,
)
from repolish.links.link_ops import (
    LinkKind,
    create_junction,
    is_junction,
    is_link,
    read_link_target,
    remove_link,
    supports_junctions,
)
from repolish.links.symlinks import (
    create_additional_link,
    link_resources,
)
from repolish.links.validation import (
    LinkCheckResult,
    check_copy_validity,
    validate_existing_link,
    validate_source_directory,
)
from repolish.links.windows_utils import (
    normalize_windows_path,
    supports_symlinks,
)

__all__ = [
    'LinkCheckResult',
    'LinkKind',
    'check_copy_validity',
    'create_additional_link',
    'create_junction',
    'is_junction',
    'is_link',
    'link_resources',
    'normalize_windows_path',
    'read_link_target',
    'remove_link',
    'resource_linker',
    'resource_linker_cli',
    'supports_junctions',
    'supports_symlinks',
    'validate_existing_link',
    'validate_source_directory',
]
