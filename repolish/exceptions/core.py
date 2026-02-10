from structlog.types import FilteringBoundLogger


class RepolishError(Exception):
    """Base exception for all Repolish errors.

    Each exception can define a log_category for consistent logging.
    """

    log_category: str = 'repolish_error'

    @classmethod
    def get_log_category(cls) -> str:
        """Get the log category for this exception type."""
        return cls.log_category


def log_exception(logger: FilteringBoundLogger, exc: Exception) -> None:
    """Log an exception with the appropriate category.

    If the exception is a RepolishError, uses its log_category.
    Otherwise uses a generic category based on exception type.

    Args:
        logger: The logger instance to use (from hotlog.get_logger)
        exc: The exception to log
    """
    category = exc.get_log_category() if isinstance(exc, RepolishError) else f'{exc.__class__.__name__.lower()}'
    logger.exception(category, error=str(exc))
