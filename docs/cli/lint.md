# repolish lint

Lint a provider's templates against its context model.

```
repolish lint PROVIDER_DIR
```

## Arguments

| Argument | Description |
| --- | --- |
| `PROVIDER_DIR` | Path to the provider root directory containing `repolish.py`. |

## What it does

`repolish lint` loads the provider at `PROVIDER_DIR`, calls `create_context()`
to get the context, then renders every template in the `repolish/` subdirectory
through Jinja2 in strict mode. Any template variable that is referenced but
missing from the context is reported as an error.

This catches typos and missing fields before you run `repolish apply`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | All templates rendered cleanly. |
| 1 | One or more templates failed (missing variable, load error, etc.). |

## Example

```bash
repolish lint ./my-provider
```

Output shows a summary per template:

```
─────────────────────── repolish lint ───────────────────────
✓  repolish/README.md.jinja
✓  repolish/.github/workflows/ci.yaml.jinja
✗  repolish/pyproject.toml.jinja
   UndefinedError: 'python_version' is undefined
```

## Limitations

Lint runs the provider in isolation - only that provider's context is available.
Cross-provider values populated by `finalize_context()` will be absent, so
templates that depend on received inputs may report false positives. In those
cases use `repolish apply --check` for a full-pipeline dry run instead.
