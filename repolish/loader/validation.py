import inspect

from repolish.loader._log import logger
from repolish.loader.models import Provider as _ProviderBase


def _is_suspicious_create_only_function(name: str) -> bool:
    """Check if a function name looks like a typo of create_create_only_files."""
    return 'create_only' in name or 'createonly' in name


def _is_suspicious_variable(name: str, valid_variables: set[str]) -> bool:
    """Check if a variable name looks like a typo of a provider variable."""
    if name in ('create_only_file', 'createonly_files', 'create_files'):
        return True
    if name.endswith('_files') and name not in valid_variables:
        return not name.startswith('create_')
    if name.endswith('_mappings') and name not in valid_variables:
        return not name.startswith('create_')
    return False


def _warn_suspicious_function(name: str, valid_functions: set[str]) -> None:
    """Emit warning for suspicious function name."""
    if _is_suspicious_create_only_function(name):
        logger.warning(
            'suspicious_provider_function',
            function_name=name,
            suggestion='Did you mean create_create_only_files?',
        )
    else:
        logger.warning(
            'unknown_provider_function',
            function_name=name,
            valid_functions=sorted(valid_functions),
        )


# Mapping from legacy module symbols to recommended Provider methods
_PROVIDER_MIGRATION_MAP: dict[str, str] = {
    'create_context': 'create_context',
    'context': 'create_context -> return Pydantic BaseModel',
    'create_file_mappings': 'create_file_mappings',
    'file_mappings': 'create_file_mappings',
    # Legacy delete/create-only hooks are consolidated under create_file_mappings
    'create_delete_files': 'create_file_mappings',
    'delete_files': 'create_file_mappings',
    'create_create_only_files': 'create_file_mappings',
    'create_only_files': 'create_file_mappings',
    'create_anchors': 'create_anchors',
    'anchors': 'create_anchors',
}


VALID_PROVIDER_FUNCTIONS: set[str] = {
    'create_context',
    'create_delete_files',
    'create_file_mappings',
    'create_create_only_files',
    'create_anchors',
}

VALID_PROVIDER_VARIABLES: set[str] = {
    'context',
    'delete_files',
    'file_mappings',
    'create_only_files',
    'anchors',
}


def _emit_provider_migration_suggestion(module_dict: dict[str, object]) -> None:
    """Emit a migration suggestion if the module looks like a module-style provider.

    The function is idempotent and returns quietly if no legacy symbols are
    present.
    """
    legacy_symbols = [
        name for name in module_dict if name in VALID_PROVIDER_FUNCTIONS or name in VALID_PROVIDER_VARIABLES
    ]
    if not legacy_symbols:
        return

    suggested = sorted(
        {_PROVIDER_MIGRATION_MAP[s] for s in legacy_symbols if s in _PROVIDER_MIGRATION_MAP},
    )
    if suggested:
        logger.warning(
            'provider_migration_suggestion',
            message=(
                'Module-style provider detected; consider migrating to the '
                'class-based `Provider` API. Implement the following methods '
                'on your Provider subclass to preserve current behaviour.'
            ),
            recommended_methods=suggested,
        )


def _has_provider_class(module_dict: dict[str, object]) -> bool:
    """Return True if the module exports a Provider subclass."""
    return any(
        inspect.isclass(val) and issubclass(val, _ProviderBase) and val is not _ProviderBase
        for val in module_dict.values()
    )


def _warn_about_suspicious_module_symbols(
    module_dict: dict[str, object],
) -> None:
    """Walk module symbols and emit warnings for suspicious names.

    Uses the smaller helpers above to keep each check focused and testable.
    """
    for name, value in module_dict.items():
        # Skip private/dunder names
        if name.startswith('_'):
            continue

        is_callable = callable(value)

        # Check for functions that start with 'create_' but aren't valid
        if is_callable and name.startswith('create_') and name not in VALID_PROVIDER_FUNCTIONS:
            _warn_suspicious_function(name, VALID_PROVIDER_FUNCTIONS)

        # Check for variables that look like provider variables but have typos
        elif not is_callable and _is_suspicious_variable(
            name,
            VALID_PROVIDER_VARIABLES,
        ):
            logger.warning(
                'suspicious_provider_variable',
                variable_name=name,
                valid_variables=sorted(VALID_PROVIDER_VARIABLES),
            )


def _validate_provider_module(
    module_dict: dict[str, object],
    *,
    require_file_mappings: bool = False,
) -> None:
    """Validate provider module for common typos and emit warnings.

    Checks for functions that look like provider functions but have typos,
    such as 'create_creat_only_files' or other misspellings. Also emits a
    migration suggestion when a module-style provider is used instead of the
    new class-based `Provider` API.

    By default the loader is permissive for module-style providers and will
    accept a provider that does not declare `create_file_mappings` (backward
    compatibility). Set ``require_file_mappings=True`` (opt-in) to enforce
    the presence of `create_file_mappings`/`file_mappings` and raise a
    RuntimeError for missing mappings.
    """
    # If the module already exports a class-based Provider, skip the
    # migration suggestion step.
    if not _has_provider_class(module_dict):
        _emit_provider_migration_suggestion(module_dict)

    _warn_about_suspicious_module_symbols(module_dict)

    # Enforce only when the caller opted into strict behaviour. Default is
    # permissive to preserve compatibility with existing module-style
    # providers.
    if 'create_file_mappings' not in module_dict and 'file_mappings' not in module_dict:
        if require_file_mappings:
            msg = (
                'provider module must define create_file_mappings() or file_mappings; '
                'return an empty dict when no mappings are required'
            )
            raise RuntimeError(msg)
        # permissive by default: treat missing mappings as an empty mapping
        return
