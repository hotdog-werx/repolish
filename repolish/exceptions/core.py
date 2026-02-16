class RepolishError(Exception):
    """Base exception for all Repolish errors.

    Each exception can define a log_category for consistent logging.
    """

    log_category: str = 'repolish_error'

    @classmethod
    def get_log_category(cls) -> str:
        """Get the log category for this exception type."""
        return cls.log_category

    def __str__(self) -> str:
        """Return string representation including the log category."""
        return f'[{self.get_log_category()}] {super().__str__()}'
