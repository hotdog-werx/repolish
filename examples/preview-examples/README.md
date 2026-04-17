# Preview examples

These YAML files are self-contained fixtures for `repolish preview`. Each file
defines a `template:`, a `target:` (the existing project file), and optionally a
`config:` block — everything the preprocessor needs in one place. No provider,
no `repolish.yaml`, no apply run required.

Run them from the repo root:

```bash
repolish preview examples/preview-examples/anchor_debug.yaml
repolish preview examples/preview-examples/multiregex_debug.yaml
```

Or with optional flags to inspect the preprocessor internals:

```bash
repolish preview examples/preview-examples/anchor_debug.yaml --show-patterns --show-steps
```

## anchor_debug.yaml

Demonstrates both anchor mechanisms side by side:

- **`repolish-regex`** — captures a value (e.g. `__version__`, `__author__`)
  from the existing target file using a regex, then substitutes it back into the
  rendered output. This is how local edits to version strings survive an apply.

- **`repolish-start` / `repolish-end`** — marks a block whose replacement text
  comes from the provider's `create_anchors()` (or `config.anchors` in the
  fixture). The target file is read to find the block boundaries, but the
  content between them comes from the provider — not from the target.

The fixture shows an `install-extras` block where the provider controls the
replacement, and `version` / `author` fields where the target file controls the
captured value.

## multiregex_debug.yaml

Demonstrates the `repolish-multiregex-block` + `repolish-multiregex` pair used
to surgically update a structured block (here, the `[tools]` section of a
`mise.toml`):

- **`repolish-multiregex-block[name]: <pattern>`** — captures the entire block
  from the target file whose start matches `<pattern>`. The captured block
  becomes a lookup table for the inner directive.

- **`repolish-multiregex[name]: <line-pattern>`** — for each line in the
  template block, searches the captured block for a matching line and
  substitutes the captured value. Lines in the template that have no match keep
  their template default. Lines in the target that are not in the template are
  dropped (the template is the source of truth for which tools exist).

The fixture shows how `new-tool = "1.0.0"` (in the template but not the target)
gets added, while existing tools preserve the versions the developer already
has.

## Using these as a starting point

Copy either file, adjust the `template:` and `target:` sections to match your
own files, and run `repolish preview --fixture <your-file.yaml>` to iterate on
preprocessor patterns without touching a real project.
