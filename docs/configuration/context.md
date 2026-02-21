# Using the loader context

Repolish collects a single merged context and passes it into provider factories
so templates and providers can adapt to configuration.

## How it works

- The loader may be seeded with the project-level configuration (this is
  authoritative). When provided the loader makes that config available to
  providers during context collection so `create_context(ctx)` factories can
  read project values.
- It then collects `create_context()` results and module-level `context` values
  from providers in the order they are listed and merges them.
- After collection, the loader re-applies project config as a final overlay so
  project-level values take precedence when resolving conflicts.
- Finally, the loader calls provider factory functions (e.g.
  `create_file_mappings`, `create_anchors`, `create_delete_files`) with the
  merged context.

Factories are backwards-compatible: they may accept 0 or 1 positional argument.
If a factory defines no parameter, it will be invoked with no args; if it
accepts one parameter, the loader will pass the merged context dict.

### Class-based providers (opt-in)

New providers may be implemented as classes by subclassing
`repolish.loader.models.Provider`. Only `get_provider_name()` and
`create_context()` are required; other hooks like `collect_provider_inputs()`
and `finalize_context()` are optional and have sensible defaults so module-style
providers remain supported.

Example:

```py
from pydantic import BaseModel
from repolish.loader.models import Provider

class MyCtx(BaseModel):
    feature_flag: bool = False

class MyProvider(Provider[MyCtx, BaseModel]):
    def get_provider_name(self) -> str:
        return 'my-provider'

    def create_context(self) -> MyCtx:
        return MyCtx(feature_flag=True)
```

Using the class-based API is opt-in; existing `repolish.py` module-style
providers will continue to work unchanged.

## Example: deriving a merge strategy

Provider A (sets base preference):

```py
def create_context():
    return {'preferred_source': 'provider_a'}
```

Provider B (derives a `merge_strategy` and exposes file mappings):

```py
def create_context(ctx):
    preferred = ctx.get('preferred_source')
    if preferred == 'provider_a':
        strat = 'ours'
    else:
        strat = 'theirs'
    return {'merge_strategy': strat}

def create_file_mappings(ctx):
    strat = ctx.get('merge_strategy', 'unknown')
    return {f'config.merged.{strat}': 'config_template'}
```

The loader will call Provider B's factories with the merged context so
`create_context(ctx)` can see values supplied by Provider A and derive
additional variables used by subsequent factories.

### File mappings: tuple form (per-file extra context)

Starting with the opt-in Jinja renderer, `create_file_mappings()` or the
module-level `file_mappings` may return `TemplateMapping` entries to provide
per-file typed extra context. This is useful when you want to reuse a single
template to generate multiple files with different, typed parameters.

Example (provider `repolish.py`):

```py
from pydantic import BaseModel
from repolish.loader.types import TemplateMapping

class ModuleCtx(BaseModel):
    module: str

def create_file_mappings(ctx):
    return {
        'src/a.py': TemplateMapping('templates/module_template.jinja', ModuleCtx(module='a')),
        'src/b.py': TemplateMapping('templates/module_template.jinja', ModuleCtx(module='b')),
        'src/c.py': TemplateMapping('templates/module_template.jinja', ModuleCtx(module='c')),
        'LICENSE': 'templates/license.txt',
    }
```

Notes:

- `TemplateMapping(source_template, extra_context)` is the required and
  preferred form for per-file extra context; `extra_context` should be a typed
  `pydantic.BaseModel` when schema validation is desired.
- Template-mapping rendering is performed by the **Jinja renderer only** — you
  must enable `no_cookiecutter: true` in your configuration for
  `TemplateMapping` entries to be materialized. Attempting to use
  `TemplateMapping` while cookiecutter rendering is enabled will raise at
  runtime.

- During rendering, Pydantic models in `extra_context` are converted to plain
  dicts. The original typed instance is preserved in `Providers.file_mappings`
  until rendering so validation tooling can inspect it.

### Provider-scoped template context (strict mode)

New (opt-in) behaviour: when `provider_scoped_template_context: true` is set in
`repolish.yaml`, `TemplateMapping` entries are rendered using _only_ the context
produced by the provider that declared the mapping. This strengthens separation
of concerns and prevents templates from depending on keys supplied by other
providers.

Important rules:

- Providers must opt into the new model by setting `provider_migrated = True` in
  their `repolish.py` module (this indicates the provider knows how to operate
  in the provider-scoped world).
- Enabling `provider_scoped_template_context` is strict: the renderer will raise
  an error if _any_ provider is not migrated. This prevents accidental
  mixed-mode behaviour and makes migrations explicit.
- Class-based providers (the `Provider` base class) are the recommended
  migration target; module-style providers must still set
  `provider_migrated = True` once they adopt provider-scoped semantics.

Migration checklist

1. Update provider `create_context()` to return only the keys the provider's
   templates require (prefer a Pydantic model for typed contexts).
2. Update `create_file_mappings()` to return
   `TemplateMapping(..., extra_context)` where appropriate.
3. Set `provider_migrated = True` in the provider's `repolish.py` when the
   provider is fully migrated and self-contained.
4. Flip `provider_scoped_template_context: true` in your `repolish.yaml` and run
   the test suite to find templates that still rely on cross-provider keys.

Example provider (migrated):

```py
# repolish.py (provider)
from repolish.loader.types import TemplateMapping
provider_migrated = True

def create_context():
    return {'my_key': 'VAL'}

def create_file_mappings():
    return {'out.txt': TemplateMapping('item.jinja', None)}
```

For a detailed, step-by-step migration checklist, examples and tests, see the
Provider migration guide: ../guides/provider-migration.md

If `provider_scoped_template_context` is enabled but any provider has not set
`provider_migrated = True` the renderer will raise an error and surface the list
of unmigrated providers so you can continue migrating safely.

> Note: this behaviour is an opt-in, preparatory step for the v1 release. Use it
> to progressively migrate providers and gain stronger isolation.

> Compatibility note: cookiecutter-based rendering is still supported but opting
> in to `TemplateMapping` requires `no_cookiecutter: true`. Because cookiecutter
> will be removed in the next major version, migrate templates and provider
> mappings to `TemplateMapping` on your upgrade schedule; if you must remain
> compatible with older releases, pin to the most recent non-breaking release
> until you migrate.

## Precedence and overrides

- Project-level configuration is authoritative and should be considered the
  final override when users supply values in the config file.
- Provider contexts are merged in order; later providers may override earlier
  provider keys. Use explicit namespacing (for example `provider_name.key`) when
  you expect keys to be overridden accidentally.

## Context overrides

For fine-grained control over deeply nested context values without duplicating
large data structures, you can use `context_overrides`. This allows surgical
updates using dot-notation paths.

Example:

```yaml
context:
  devkits:
    - name: d1
      ref: v0
    - name: d2
      ref: v1

context_overrides:
  'devkits.0.name': 'new-d1'
  'devkits.1.ref': 'v2'
```

Overrides are applied after provider contexts are merged but before project
config takes final precedence. Invalid paths are logged as warnings but do not
stop processing.

Supported path formats:

- Simple keys: `'key'`
- Nested objects: `'parent.child'`
- Arrays by index: `'list.0.name'`
- Mixed: `'config.list.1.setting'`

For recommended patterns on structuring provider contexts to work well with
overrides, see [Provider Patterns](../patterns.md).

## Tips for template authors

- Keep `create_context()` small and focused; return simple, well-named keys.
- Derive higher-level computed values (feature flags, merge strategy, path
  prefixes) in `create_context(ctx)` so they are available to all factories.
- Document the context keys your template expects so users can configure them in
  the project config.

## Example test

There is a small integration test that demonstrates this pattern:
`tests/test_integration_merge_strategy.py`.
