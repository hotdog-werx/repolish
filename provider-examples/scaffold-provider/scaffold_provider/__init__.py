"""scaffold_provider - multi-scenario test provider for the repolish integration suite.

Demonstrates and exercises file lifecycle behaviors:
- Regular files (README.md): always synced on every ``repolish apply``.
- CREATE_ONLY files (__init__.py): seeded on first apply, never overwritten.
- Conditional CREATE_ONLY files (config.py): only materialized when the
  context flag ``include_optional_config`` is set to ``true``.
"""
