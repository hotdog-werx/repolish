# provider-examples

Real, installable provider packages used as living documentation and as the
foundation for the integration test suite.

Each subdirectory is a self-contained Python package that can be built and
installed with `uv`. The integration tests in `tests/integration/` build these
packages into wheels, install them into the active test venv, run the tests, and
then uninstall them on teardown — so every test exercises repolish the same way
a real user would.

## Why a separate top-level folder?

- **Realism over mocking.** Tests that work against installed packages catch
  issues (entry-point registration, `importlib` discovery, CLI plumbing) that
  pure unit tests with mocks cannot.
- **Living documentation.** Each provider demonstrates a specific pattern that
  also becomes the basis for a docs page.
- **Scaffold source of truth.** New providers can be bootstrapped via
  `repolish scaffold` and landed here, so the scaffold output is itself tested.

## Providers

| Directory                           | Pattern                      | Docs |
| ----------------------------------- | ---------------------------- | ---- |
| [simple_provider](simple_provider/) | Minimal class-based provider | —    |

## Adding a new provider example

1. Create a subdirectory, e.g. `provider-examples/my_provider/`.
2. Add a `pyproject.toml` (use `simple_provider` as a template).
3. Implement the provider package, including a `cli.py` that calls
   `resource_linker_cli()` and registers the link script under
   `[project.scripts]`.
4. Add the provider to the session fixture in `tests/integration/conftest.py`.
5. Write integration tests in `tests/integration/`.
