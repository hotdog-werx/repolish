# Context

Every Jinja2 template and every provider hook receives a single merged context
dictionary. This page explains where context values come from and how they are
combined.

## Sources and merge order

Context is assembled from four sources, applied in this order (later wins):

| # | Source                      | Where it is defined                                | Merge behaviour                                     |
| - | --------------------------- | -------------------------------------------------- | --------------------------------------------------- |
| 1 | Global context              | Injected by repolish automatically                 | always present                                      |
| 2 | Provider `create_context()` | Each provider's module or `Provider` class         | shallow merge                                       |
| 3 | Config `context:`           | `repolish.yaml` top-level `context:` key           | **shallow** — replaces each top-level key wholesale |
| 4 | Config `context_overrides:` | Per-provider or top-level `context_overrides:` key | **deep** — dot-notation paths patch nested fields   |

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
`finalize_context()` instead — it runs after all providers have emitted their
initial context and received any cross-provider inputs.

## Config-level context

Values under `context:` in `repolish.yaml` are merged into the final context
using a **shallow `update`**. Each top-level key replaces whatever the provider
produced for that key in full. If a provider returns a nested object and you
only want to change one field inside it, you would have to repeat the entire
object under `context:` — which defeats the point.

```yaml
context:
  python_version: '3.12' # simple scalar: fine
  author: 'Acme Corp'
```

For overriding a single nested field, use `context_overrides:` instead (see
below).

## Context overrides per provider

`context_overrides:` under a provider entry (or at the top level of
`repolish.yaml`) applies changes using **dot-notation paths**. This lets you
reach into a nested object and patch exactly the field you care about, without
touching anything else:

```yaml
providers:
  my-provider:
    cli: my-provider-link
    context_overrides:
      repolish.provider.python_version: '3.12' # patches one nested field
      use_ruff: false # simple key also works
```

The same syntax works at the top level of `repolish.yaml`:

```yaml
context_overrides:
  my_provider.tools.0.version: '0.8.0' # patch a list element
  my_provider.some_flag: true
```

Nested dict form is also accepted and flattened automatically:

```yaml
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
