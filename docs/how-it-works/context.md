# Context

Every Jinja2 template and every provider hook receives a single merged context
dictionary. This page explains where context values come from and how they are
combined.

## Sources and merge order

Context is assembled from four sources, applied in this order (later wins):

| # | Source                     | Where it is defined                        |
|---|----------------------------|--------------------------------------------|
| 1 | Global context             | Injected by repolish automatically         |
| 2 | Provider `create_context()`| Each provider's module or `Provider` class |
| 3 | Config `context:`          | `repolish.yaml` top-level `context:` key   |
| 4 | Config `context_overrides:`| Per-provider `context_overrides:` key      |

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

`BaseContext` already includes the `repolish` namespace, so typed providers
get `ctx.repolish.repo.owner` without any extra fields.

If you need to derive values from a prior provider's output, override
`finalize_context()` instead — it runs after all providers have emitted their
initial context and received any cross-provider inputs.

## Config-level context

Values under `context:` in `repolish.yaml` override provider defaults for the
whole project:

```yaml
context:
  python_version: '3.12'
  author: 'Acme Corp'
```

## Context overrides per provider

`context_overrides:` under a provider entry sets values that are passed to that
specific provider's `create_context()` *and* merged into the final context:

```yaml
providers:
  my-provider:
    cli: my-provider-link
    context_overrides:
      use_ruff: false
```

This is especially useful when the same provider is consumed with different
settings in a monorepo.

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
