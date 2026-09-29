"""The durable link-creation utility.

Everything a project needs to link packaged resources into a working tree:
:func:`~repolish.links.symlinks.link_resources` and friends do the actual
symlink-or-copy work, and the ``resource_linker`` decorators turn that core
into a ready-made linking CLI for any library. This package is deliberately
self-contained so it survives on its own: repolish's registration engine
(:mod:`repolish.linker`) consumes it, and third-party projects can too,
without pulling in any provider machinery.
"""

from repolish.links.decorator import (
    resource_linker,
    resource_linker_cli,
)
from repolish.links.symlinks import (
    create_additional_link,
    link_resources,
)
from repolish.links.validation import (
    check_copy_validity,
    validate_existing_symlink,
    validate_source_directory,
)
from repolish.links.windows_utils import (
    normalize_windows_path,
    supports_symlinks,
)

__all__ = [
    'check_copy_validity',
    'create_additional_link',
    'link_resources',
    'normalize_windows_path',
    'resource_linker',
    'resource_linker_cli',
    'supports_symlinks',
    'validate_existing_symlink',
    'validate_source_directory',
]
