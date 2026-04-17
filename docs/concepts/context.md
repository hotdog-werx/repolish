# Context

Every Jinja2 template and every provider hook receives a single merged context
dictionary. This page explains where context values come from and how they are
combined.

## Sources and merge order

Context is assembled from four sources, applied in this order (later wins):

| # | Source                      | Where it is defined                        | Merge behaviour                                     |
| - | --------------------------- | ------------------------------------------ | --------------------------------------------------- |
| 1 | Global context              | Injected by repolish automatically         | always present                                      |
| 2 | Provider `create_context()` | Each provider's module or `Provider` class | shallow merge                                       |
| 3 | Config `context:`           | `repolish.yaml` top-level `context:` key   | **shallow** - replaces each top-level key wholesale |
| 4 | Config `context_overrides:` | Per-provider `context_overrides:` key      | **deep** - dot-notation paths patch nested fields   |

The distinction between `context:` and `context_overrides:` matters when a
provider exposes a nested object (e.g. `tools.uv.version`). With `context:` you
must supply the whole top-level key; with `context_overrides:` you target only
the field you want to change.

Providers are loaded in the order listed under `providers:` in `repolish.yaml`.
Each provider's `create_context()` can read the merged context produced so far,
so later providers can react to earlier ones.

## Global context

The `repolish` key is always present and is populated before any provider runs:

```python
ctx.repolish.repo.owner   # GitHub org / username inferred from git remote
ctx.repolish.repo.name    # repository name
ctx.repolish.year         # current calendar year (useful for license headers)
```

In templates:

```
# © {{ repolish.year }} {{ repolish.repo.owner }}
```

## Provider context

Each provider's `create_context()` method returns a typed Pydantic model.

```python
from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    python_version: str = '3.11'
    use_ruff: bool = True


class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()
```

`BaseContext` already includes the `repolish` namespace, so typed providers get
`ctx.repolish.repo.owner` without any extra fields.

If you need to derive values from a prior provider's output, override
`finalize_context()` instead - it runs after all providers have emitted their
initial context and received any cross-provider inputs.

## Config-level context

Values under `context:` in `repolish.yaml` are merged into the final context
using a **shallow `update`**. Each top-level key replaces whatever the provider
produced for that key in full. If a provider returns a nested object and you
only want to change one field inside it, you would have to repeat the entire
object under `context:` - which defeats the point.

```yaml
context:
  python_version: '3.12' # simple scalar: fine
  author: 'Acme Corp'
```

For overriding a single nested field, use `context_overrides:` instead (see
below).

## Context overrides per provider

`context_overrides:` under a provider entry applies changes using **dot-notation
paths**. This lets you reach into a nested object and patch exactly the field
you care about, without touching anything else:

```yaml
providers:
  my-provider:
    cli: my-provider-link
    context_overrides:
      repolish.provider.python_version: '3.12' # patches one nested field
      use_ruff: false # simple key also works
```

Nested dict form is also accepted and flattened automatically:

```yaml
providers:
  my-provider:
    cli: my-provider-link
    context_overrides:
      my_provider:
        some_flag: true
        'tools.0.version': '0.8.0'
```

This is especially useful when the same provider is consumed with different
settings in a monorepo, or when a provider namespace contains a deep structure
that you want to patch without duplicating it.

## What context is available in templates

All top-level keys from the merged context are available directly in Jinja2
templates:

```toml
[tool.ruff]
target-version = "py{{ python_version | replace('.', '') }}"
```

The `repolish` namespace is always available:

```yaml
# repo: {{ repolish.repo.owner }}/{{ repolish.repo.name }}
```

## Inspecting context after an apply

Every `repolish apply` run writes debug JSON files into `.repolish/_/` so you
can see exactly what context each provider and each file received.

### Per-provider: `provider-context.<role>.<alias>.json`

One file per provider, named after its session role and alias:

```
.repolish/_/provider-context.standalone.my-provider.json
.repolish/_/provider-context.root.devkit-workspace.json
.repolish/_/provider-context.pkg-alpha.devkit-python.json
```

Each file contains:

```json
{
  "alias": "my-provider",
  "context": { ... },   // the full merged context this provider contributed
  "files": [            // files this provider manages
    { "path": "pyproject.toml", "mode": "regular", "source": "pyproject.toml.jinja" }
  ]
}
```

In terminals that support hyperlinks, the provider name in the summary tree is a
clickable link that opens this file directly.

### Per-file: `file-ctx/file-context.<slug>.json`

One file per rendered template, named after the destination path (`/` replaced
with `--`):

```
.repolish/_/file-ctx/file-context.pyproject.toml.json
.repolish/_/file-ctx/file-context.src--mylib--__init__.py.json
```

Each file records what was injected during rendering:

```json
{
  "dest": "pyproject.toml",
  "owner": "my-provider",
  "source_template": "pyproject.toml.jinja",
  "provider_context_file": "provider-context.standalone.my-provider.json",
  "extra_context": {} // any mapping-level extra_context on top of provider context
}
```

`extra_context` is populated when a `TemplateMapping` carries additional keys
that override or extend the provider context for that specific file only. If
`extra_context` is empty, the file was rendered purely from its provider's
context.

In terminals that support hyperlinks, each file name in the summary tree is a
clickable link that opens this file directly.

### Workflow

When a template renders unexpectedly, the typical workflow is:

1. Run `repolish apply` (or `repolish apply --check`).
2. Click the file name in the summary tree to open its `file-context` JSON.
3. Check `extra_context` - if it is non-empty, those keys shadowed the provider
   context.
4. Click `provider_context_file` in that JSON to open the provider snapshot and
   inspect the full `context` object to see every key available in the template.
