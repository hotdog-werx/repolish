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
