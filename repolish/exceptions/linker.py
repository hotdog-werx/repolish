from repolish.exceptions.core import RepolishError


class LinkerError(RepolishError):
    """Base class for linker-related errors."""

    log_category = 'linker_error'


class SymlinkError(LinkerError):
    """Error during symlink creation or management."""

    log_category = 'symlink_failed'


class ResourceLinkerError(LinkerError):
    """Error in resource_linker decorator usage."""

    log_category = 'resource_linker_error'
