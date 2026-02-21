# Provider migration guide — module → provider-scoped templates

This guide helps you migrate a provider so it can be rendered using the
`provider_scoped_template_context` strict mode. The goal is to make each
provider self-contained: templates declared by a provider should only use the
context supplied by that provider (or the mapping's `extra_context`).

Why migrate?

- Stronger separation of concerns — templates cannot accidentally depend on keys
  from other providers.
- Easier reasoning and safer upgrades toward the v1 major release.
- Better observability — each `TemplateMapping` is provably owned by a provider
  and can be tested in isolation.

When to migrate

- Start with small/simple providers (few templates / small contexts).
- Migrate providers that are frequently changed or whose templates already
  reference only local keys.
- Keep large providers for later — migrate incrementally and run CI after each
  migration.

Quick checklist (practical)

1. Convert per-file mappings to `TemplateMapping` where you need typed
   extra-context (optional but recommended).
2. Ensure `create_context()` returns only keys required by _this_ provider's
   templates. Use a Pydantic `BaseModel` return type for validation.
3. Update templates so they reference only keys present in `create_context()` or
   in the mapping's `extra_context`.
4. Add `provider_migrated = True` at top-level in the provider's `repolish.py`
   to mark the provider as migrated.
5. Add/adjust unit tests for the provider to assert provider-scoped rendering
   behaviour (see test suggestions below).
6. In your project config: flip `provider_scoped_template_context: true` and run
   `poe ci-checks` / CI to detect remaining cross-provider usage.

Example: before → after (small provider)

Before (module-style, uses merged context implicitly):

```py
# repolish.py (old)
def create_context():
    return {'shared_prefix': 'lib'}

def create_file_mappings(ctx):
    # reads ctx from the merged context (may rely on keys from other providers)
    return {'src/a.py': 'templates/mod.jinja'}
```

After (migrated, provider-scoped):

```py
# repolish.py (migrated)
from repolish.loader.types import TemplateMapping
provider_migrated = True

from pydantic import BaseModel

class Ctx(BaseModel):
    shared_prefix: str = 'lib'

def create_context():
    return Ctx(shared_prefix='lib')

def create_file_mappings():
    # explicit TemplateMapping — extra_context can also be a pydantic model
    return {'src/a.py': TemplateMapping('templates/mod.jinja', None)}
```

Final form — class-based `Provider` (recommended)

The end-state for a migrated provider is a small, typed `Provider` subclass.
Class-based providers improve discoverability, make testing easier, and are
fully compatible with the loader (the loader will instantiate the class and
expose the same module-level factory hooks so existing consumers continue to
work).

```py
# repolish.py (class-based final form)
from pydantic import BaseModel
from repolish.loader.models import Provider
from repolish.loader.types import TemplateMapping, FileMode

# mark provider migrated for strict provider-scoped mode
provider_migrated = True

class Ctx(BaseModel):
    shared_prefix: str = 'lib'
    license: str = 'MIT'

class MyProvider(Provider[Ctx, BaseModel]):
    def get_provider_name(self) -> str:
        return 'my-provider'

    def create_context(self) -> Ctx:
        return Ctx(shared_prefix='acme', license='Apache-2.0')

    # Optional: instance-level factory (loader will forward this to the
    # module-level `create_file_mappings()` callable so existing code paths
    # remain unchanged).
    def create_file_mappings(self):
        return {
            'src/__init__.py': TemplateMapping('pkg_init.jinja', None),
            'README.md': TemplateMapping('readme.jinja', None, file_mode=FileMode.CREATE_ONLY),
        }

    # Note: helpers for delete/create-only lists are still supported as
    # module-level functions/variables (e.g. `create_delete_files()` /
    # `delete_files`, `create_create_only_files()` / `create_only_files`).
    # The loader currently forwards *instance-level* `create_file_mappings()`
    # and `create_anchors()` from a `Provider` subclass into the module
    # namespace so class-based providers can implement those as instance
    # methods. If you need to provide delete/create-only helpers from a
    # class-based provider, expose small module-level wrappers that call
    # into your provider instance (the loader preserves backward-compat
    # for these module-level helpers).
```

How the loader recognizes the class

- The loader imports the provider module (`repolish.py`) into a `module_dict`.
- It scans exported values and uses `inspect.isclass()` +
  `issubclass(..., Provider)` to find any `Provider` subclasses (see
  `repolish.loader.orchestrator._find_provider_class`).
- If found, the loader instantiates the class and _injects_ instance-backed
  callables into the module dict (e.g. `create_context`, `create_file_mappings`,
  `create_anchors`) so the rest of the loader works exactly the same as with
  module-style providers (see
  `repolish.loader.orchestrator._inject_provider_instance`).

Practical notes

- Set `provider_migrated = True` at module level to mark the provider as
  migrated; only migrated providers will have their mappings rendered against
  their own context. Non-migrated providers continue to receive merged context
  even when `provider_scoped_template_context` is turned on.
- The class-based API is optional but recommended for larger providers and when
  you want compile/test-time reassurance (Pydantic types give IDE + validation
  benefits).
- Existing module-style providers continue to work until you opt into strict
  provider-scoped rendering.

Testing suggestions

- Unit: verify `Providers.provider_contexts[provider_id]` contains the keys you
  expect after loading providers.
- Integration: enable `provider_scoped_template_context` locally and run
  rendering tests that exercise per-mapping templates for that provider.
- Regression: add a test that fails if the provider's template references a key
  not present in its own context (ensures future changes remain self-contained).

Troubleshooting & migration patterns

- Template needs a value from another provider:
  - Prefer moving the responsibility to the provider that declares the template
    (duplicate the small value into its `create_context()`), or
  - Use `TemplateMapping(..., extra_context=...)` to provide the needed key at
    mapping time, or
  - Keep the template under the provider that owns the required context.

- Large providers with many interdependent templates:
  - Migrate incrementally — split provider responsibilities if sensible.
  - Add tests for each sub-area during the migration.

- Want a smoother rollout for many providers:
  1. Migrate provider code and add `provider_migrated = True` locally.
  2. Run CI with `provider_scoped_template_context: true` in a feature branch.
  3. Fix templates that fail; repeat until the branch is green.
  4. Merge and enable the flag in the mainline once providers are migrated.

Commands & quick checks

- Run unit/tests: `poe ci-checks` or `pytest -q`
- Verify provider flags: inspect `Providers.provider_migrated` in the loader
  output or add a unit test asserting the flag is present.

Final notes

- This migration is opt‑in: enabling `provider_scoped_template_context` does not
  immediately break existing module-style providers. Only providers that have
  opted in via `provider_migrated = True` are isolated; others still render with
  the merged context. You can gradually migrate providers and flip the flag at
  your own pace.
- If you want, I can update the example providers in `examples/` to show a full
  end‑to‑end migrated provider.
