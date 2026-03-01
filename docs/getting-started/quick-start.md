# Quick Start

This guide walks through setting up a minimal Repolish configuration and running
your first check.

## Minimal configuration

Create a `repolish.yaml` at the root of your project:

```yaml
directories:
  - ./templates/my-template

context: {}
anchors: {}
delete_files: []
```

Each entry in `directories` must point to a directory that contains either a
`repolish.py` module or a `repolish/` template folder (or both).

## Run a dry-run check

Use `--check` to compare what Repolish would generate against your current
project files without writing anything:

```bash
repolish --check --config repolish.yaml
```

The output includes structured logs showing:

- The merged provider `context` and `delete_paths`
- A `check_result` listing per-path diffs
- Files that providers want deleted but which are still present
  (`PRESENT_BUT_SHOULD_BE_DELETED`)
- Files that would be created but are missing (`MISSING`)

## Apply changes

Once you are satisfied with the diff output, apply the changes:

```bash
repolish --config repolish.yaml
```

Repolish will:

1. Render templates into `.repolish/setup-output`
2. Copy generated files into your project
3. Apply any file deletions requested by providers

## Example with post-processing

If your project uses a formatter, add it to `post_process` so checks always
operate on formatted output:

```yaml
directories:
  - ./templates/my-template

context:
  package_name: my-project

post_process:
  - poe format

delete_files: []
```

If a `post_process` command exits with a non-zero status, Repolish fails and
returns a non-zero exit code so CI can detect the problem.

## Next steps

- [Configuration reference](../configuration/overview.md) — all `repolish.yaml` fields
- [Templates guide](../guides/templates.md) — file mappings and create-only files
- [Preprocessors guide](../guides/preprocessors.md) — anchors and regex directives
- [Provider Patterns](../guides/patterns.md) — structuring providers for real projects
