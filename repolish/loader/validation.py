from ._log import logger


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


def _validate_provider_module(module_dict: dict[str, object]) -> None:
    """Validate provider module for common typos and emit warnings.

    Checks for functions that look like provider functions but have typos,
    such as 'create_creat_only_files' or other misspellings.
    """
    # Known valid function names
    valid_functions = {
        'create_context',
        'create_delete_files',
        'create_file_mappings',
        'create_create_only_files',
        'create_anchors',
    }

    # Known valid variable names
    valid_variables = {
        'context',
        'delete_files',
        'file_mappings',
        'create_only_files',
        'anchors',
    }

    # Check for suspicious names that might be typos
    for name, value in module_dict.items():
        # Skip private/dunder names
        if name.startswith('_'):
            continue

        is_callable = callable(value)

        # Check for functions that start with 'create_' but aren't valid
        if is_callable and name.startswith('create_') and name not in valid_functions:
            _warn_suspicious_function(name, valid_functions)

        # Check for variables that look like provider variables but have typos
        elif not is_callable and _is_suspicious_variable(name, valid_variables):
            logger.warning(
                'suspicious_provider_variable',
                variable_name=name,
                valid_variables=sorted(valid_variables),
            )
