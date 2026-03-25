# Integration test fixtures

Each subdirectory is a minimal project used by the integration tests.
Tests stage a copy of the fixture into a `tmp_path`, so the originals
are never modified during a normal `pytest` run.

## Running a fixture manually

First make sure all example providers are installed:

```bash
poe install-devkit-providers
```

Then `cd` into the fixture and run `repolish apply`:

```bash
cd tests/integration/fixtures/simple-repo
repolish apply
```

## Warning: manual runs modify the fixture

`repolish apply` writes generated files and a `.repolish/_/` debug
directory directly into the fixture folder.  If those files are left
behind, subsequent integration tests that expect a clean state will
fail — for example, a `--check` test that expects `MISSING` will
instead find the file already present and pass silently.

## Safe workflow for manual debugging

1. Commit (or stash) your code changes with a note, e.g.:

   ```bash
   git stash push -m "WIP - testing - revert me"
   ```

2. Run `repolish apply` in the fixture.

3. Inspect the output, reproduce the bug, etc.

4. Clean up before running tests:

   ```bash
   git clean -fd tests/integration/fixtures/
   ```

   or remove specific files/directories created by the run.

5. Pop your stash:

   ```bash
   git stash pop
   ```

The `git clean -fd` approach is the fastest way to restore all fixtures
to their committed state in one command.
