# Insertions

Insertions let a provider fill reserved blocks inside files that are not fully
owned by template rendering.

Use insertions when a developer-owned file needs one or more generated regions,
while the rest of the file stays hand-edited.

- `create_file_mappings()` owns and writes entire files
- `create_file_validators()` checks final files
- `create_file_insertions()` fills explicit blocks in existing files

## Where insertions fit in apply

Insertions run in the apply pipeline after generated files are written, then
report per-file insertion status in the summary.

In check mode, insertion output is also checked for drift. If insertion-managed
content is stale, `repolish apply --check` fails just like template drift.

## Marker format

A reserved block is defined with an `on/off` pair and a tag:

```html
<!-- repolish:on:year display-year -->
<!-- repolish:off:year -->
```

The `on` marker includes:

- tag: `year`
- function name: `display-year`
- optional args after the function name

Example with args:

```html
<!-- repolish:on:mode display-mode on -->
<!-- repolish:off:mode -->
```

## Registering insertion functions

`create_file_insertions()` is keyed by explicit destination path and function
name.

```python
from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    pass


class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_insertions(self, context: Ctx):
        def display_year(*, context, tag, args):
            return '2026'

        def display_mode(*, args):
            flag = args[0]
            if flag == 'on':
                return 'VISIBLE'
            if flag == 'off':
                return 'HIDDEN'
            return f'UNKNOWN:{flag}'

        return {
            'README.md': {
                'display-year': display_year,
                'display-mode': display_mode,
            },
        }
```

Function signatures are flexible. Insertions support patterns like:

- keyword metadata (`context`, `tag`, `args`, `block`, etc.)
- positional arg functions (`fn(a, b, c)`)
- zero-arg functions (`fn()`)

## Dynamic explicit file mapping (recommended)

Insertion registry keys are explicit file paths, not glob patterns.

If you want broad coverage like all files under `docs/`, do the discovery in
provider code and build an explicit mapping dynamically. This keeps ownership
clear and makes the final insertion target set fully visible in provider output.

```python
from pathlib import Path

from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    pass


class DocsProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_insertions(self, context: Ctx):
        def render_last_updated(*, context, args):
            return context.repolish.provider.version

        root = context.repolish.workspace.root_dir
        docs_dir = Path(root) / 'docs'
        mappings = {}

        for file_path in docs_dir.rglob('*.md'):
            rel = file_path.relative_to(root).as_posix()
            mappings[rel] = {
                'render-last-updated': render_last_updated,
            }

        return mappings
```

This pattern is the intended way to support directory-wide insertion targets.

## Provider-qualified function names

If multiple providers expose the same function name, use a provider-qualified
name in the marker:

```html
<!-- repolish:on:year alpha:display-year -->
<!-- repolish:off:year -->
```

If an unqualified name is used, repolish resolves it deterministically from the
active provider order.

## Failure behavior and summary output

If a block references an unknown function, insertion does not crash the entire
apply. The block is recorded as failed, diagnostics are written, and summary
output shows mixed status.

Example summary lines:

```text
insertions: ✓ ok (1 ok, 0 failed)
insertions: ✗ failed (1 ok, 1 failed)
```

This makes partial success explicit for files with multiple insertion blocks.

## Insertion reports

For each file with insertion blocks, repolish writes a report artifact:

```text
.repolish/_/insertions/insertions.<path-slug>.json
```

Report fields include:

- `file`
- `source_provider`
- `total_blocks`
- `failed_blocks`
- `functions`
- `diagnostics`

These files are the detailed record behind the compact summary tree output.

## Check mode

Insertions participate in `apply --check`.

- In-sync insertion content: exit code `0`
- Drifted insertion content: exit code `2` with unified diff output

This keeps insertion-managed regions compatible with CI drift checks.

## Monorepo notes

Insertion functions receive provider context, so they can observe workspace mode
(`root`, `member`, `standalone`) and render mode-aware content when needed.

Provider-qualified function names also help avoid collisions in monorepos where
multiple providers may target the same destination file.

## Related pages

- [Templates](templates.md)
- [Validators](validators.md)
- [Monorepo](monorepo.md)
- [Testing Providers](testing.md)
