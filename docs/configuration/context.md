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
- A small **global context** is seeded automatically and merged in before any
  provider values. It is always available under the top-level `repolish` key and
  currently contains

  - a nested `repo` object with the GitHub repository information (`owner` and
    `name`) inferred from the `origin` remote, and
  - a `year` field containing the current calendar year (useful for license
    headers and similar boilerplate).
  - when running `repolish` with `-vv` you will also see a
    `final_providers_generated` log event. the payload is now structured with
    two top-level keys:

    ```yaml
    final_providers_generated:
      global_context: { ... }
      providers:
        - alias: foo
          context: { ... }
          provider_migrated: true
        - alias: bar
          context: { ... }
          provider_migrated: false
    ```

    - `global_context` is the merged context that was applied across all
      providers. it serves as a convenient debugging snapshot when you need to
      know what values every template could potentially access.
    - `providers` is a list of per-alias contexts. the boolean
      `provider_migrated` flag continues to be recorded for backwards
      compatibility and tests, but in practice every provider is treated as
      migrated and you should rarely need to look at it.

  Project configuration may override any of these values via the usual
  `context`/`context_overrides` mechanism. Historically the repo fields were
  flattened as `repo_owner`/`repo_name`; the loader still exposes read-only
  proxies for backwards compatibility but new code should use
  `ctx.repolish.repo.owner` and `ctx.repolish.repo.name`.

- Finally, the loader calls provider factory functions (e.g.
  `create_file_mappings`, `create_anchors`, `create_delete_files`) with the
  merged context.

Factories are backwards-compatible: they may accept 0 or 1 positional argument.
If a factory defines no parameter, it will be invoked with no args; if it
accepts one parameter, the loader will pass the merged context dict.

### Class-based providers (opt-in)

New providers may be implemented as classes by subclassing
`repolish.loader.models.Provider`. Only `create_context()` is required; other
hooks such as `provide_inputs()` and `finalize_context()` are optional and have
sensible defaults so module-style providers remain supported.

The `Provider` class is generic in two parameters: the first describes the
context model produced by `create_context()`, and the second is the **input
schema** this provider will accept when other providers send messages. You must
supply both type arguments when subclassing; if your provider does not receive
any inputs it's customary to use `BaseModel` (or another trivial `BaseModel`
subclass) as the placeholder. The generic does _not_ constrain what your own
`provide_inputs()` implementation may return; that hook can emit arbitrary
`BaseModel` instances and (for legacy module adapters) plain dicts, and the
loader will route them based on recipient schemas.

Example:

```py
from pydantic import BaseModel
from repolish.loader.models import Provider, BaseContext

# use BaseContext when you don't need any fields – it saves you from importing
# pydantic everywhere and avoids the "BaseModel cannot be instantiated"
# error that occurs if you try to return `BaseModel()` directly.
#
# Additionally, `BaseContext` defines a `repolish` attribute that will
# always be populated with the global context (currently the repository
# owner/name inferred from the git remote).  this means even trivial
# contexts can access ``ctx.repolish`` without needing to define the field
# themselves.
class MyCtx(BaseContext):
    feature_flag: bool = False

class MyProvider(Provider[MyCtx, BaseModel]):
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
from repolish import TemplateMapping

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
- Template-mapping rendering is performed by the Jinja renderer.

- During rendering, Pydantic models in `extra_context` are converted to plain
  dicts. The original typed instance is preserved in `Providers.file_mappings`
  until rendering so validation tooling can inspect it.

### Provider-scoped template context

As of the current release every provider is treated as if it has been migrated;
templates belonging to a provider always render using that provider's own
context. This isolation is automatic and you do **not** need to set
`provider_migrated = True` in new providers. The flag continues to exist because
some older tests and logging expectations still inspect it, but it is no longer
required for normal operation.

The configuration option `provider_scoped_template_context` also lingers for
compatibility, but it is effectively always `true` and may be removed in a
future version. When you run with `-vv` the `final_providers_generated` event
will include a `provider_migrated` boolean for each alias; this helps
diagnostics but need not influence your configuration.

The staging phase records which provider supplied each template file. during
rendering, files owned by a provider receive that provider's context. providers
that happen to set `provider_migrated = True` will have that information logged
but it no longer affects rendering behaviour.

> **Tip:** if you're investigating unexpected values in a template, look at the
> `final_providers_generated` log event (requires verbosity `-vv`). the
> `global_context` key shows the merged context and the `providers` list shows
> what each provider saw.

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
from repolish import TemplateMapping
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

## Precedence and overrides

- Project-level configuration is authoritative and should be considered the
  final override when users supply values in the config file.
- Provider contexts are merged in order; later providers may override earlier
  provider keys. Use explicit namespacing (for example `provider_name.key`) when
  you expect keys to be overridden accidentally.

- **Provider-specific context** (_new_): instead of a separate top‑level
  mapping, you now specify an optional `context` mapping directly on each
  provider configuration entry. These values are merged into the context
  produced by the provider during loading and then incorporated into the global
  merged context, giving your project configuration fine‑grained control over
  individual providers without scattering unrelated settings across the file.

  ```yaml
  providers:
    foo:
      cli: foo-link
      context:
        foo_key: overridden
      context_overrides:
        'foo_key': 'more-specific' # dotted paths work too
    bar:
      directory: ./local-templates
      context:
        bar_flag: true
  ```

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

The loader first dumps any `BaseModel` contexts to plain dictionaries, then
merges the overrides and finally attempts to re-validate the result back into
the original model class. A deep copy of the dumped dict is used so that
mutating the temporary structure cannot affect the original model – this ensures
nested default objects are preserved, and it allows overrides to populate fields
buried inside defaulted sub‑models.

If an override changes a value that cannot be represented by a provider's
context model – for example a dotted path that references a key not yet
introduced or a value that fails a type check – the override is dropped and a
warning is emitted (`context_override_validation_failed` or
`context_override_ignored`). The warning makes it easy to spot typos or attempts
to set keys that are added later during provider finalization.

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
