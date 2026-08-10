"""File validator execution.

Runs validators collected from providers against existing files on disk.
Validators are checked after context resolution but before/during template rendering.
"""

from __future__ import annotations

from pathlib import Path

from hotlog import get_logger

from repolish.providers.models import BaseContext, SessionBundle

logger = get_logger(__name__)


def run_validators(
    providers: SessionBundle,
    base_dir: Path,
    *,
    strict: bool = False,
) -> tuple[bool, list[str]]:
    """Run all file validators against the project directory.

    Args:
        providers: SessionBundle with file_validators populated.
        base_dir: Project root directory where files live.
        strict: If True, validator failures cause hard errors.

    Returns:
        Tuple of (all_passed, messages).
        all_passed is True if all validators passed (or no validators ran).
        messages is a list of failure messages for reporting.
    """
    if not providers.file_validators:
        return True, []

    all_passed = True
    messages: list[str] = []

    for dest_path, validators in providers.file_validators.items():
        file_path = base_dir / dest_path

        for validator_name, validator_func in validators.items():
            # Get the context for this validator
            # For now, use the first available provider context
            # In the future, this could be more sophisticated about which context to use
            context = next(iter(providers.provider_contexts.values()), None)
            if context is None:
                context = BaseContext()

            try:
                result = validator_func(context, file_path)
            except Exception as exc:
                logger.exception(
                    'validator_crashed',
                    file=dest_path,
                    validator=validator_name,
                    error=str(exc),
                )
                all_passed = False
                messages.append(f'Validator {validator_name!r} crashed on {dest_path!r}: {exc}')
                continue

            if not result.passed:
                all_passed = False
                msg = f'Validation failed for {dest_path!r} ({validator_name}): {result.message}'
                messages.append(msg)
                if strict:
                    logger.error('validator_failed_strict', file=dest_path, validator=validator_name)
                else:
                    logger.warning('validator_failed', file=dest_path, validator=validator_name)

    return all_passed, messages
