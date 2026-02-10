from repolish.exceptions.core import RepolishError


class ConfigError(RepolishError):
    """Base class for configuration-related errors."""

    log_category = 'config_error'


class ConfigValidationError(ConfigError):
    """Configuration validation failed (structure, values, etc.)."""

    log_category = 'config_validation_failed'


class ProviderConfigError(ConfigError):
    """Provider configuration is invalid."""

    log_category = 'provider_config_invalid'


class ProviderOrderError(ConfigError):
    """providers_order references undefined providers."""

    log_category = 'provider_order_invalid'


class DirectoryValidationError(ConfigError):
    """Provider directory structure is invalid or missing."""

    log_category = 'directory_validation_failed'
