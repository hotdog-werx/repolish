This folder contains a minimal example you can use to try repolish locally.

How to try:

1. Change into the examples directory:

   ```bash
   cd examples
   ```

2. Run a dry-run check (it will compare generated output to `project/`):

   ```bash
   python -m repolish.cli --check --config repolish.yaml
   ```

3. To apply the changes (careful):

   ```bash
   python -m repolish.cli --config repolish.yaml
   ```

The example shows a Dockerfile `install` block preserved in the project and an
`extra-deps` block preserved in `pyproject.toml`.
