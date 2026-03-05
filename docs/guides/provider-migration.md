# Provider migration guide — module → provider-scoped templates

In current versions of Repolish provider-scoped rendering is the **default
behaviour**: every provider's templates are rendered using only the context
collected for that provider. There is no longer a requirement to enable a
special "strict mode" or to mark providers as migrated; the `provider_migrated`
flag and the `provider_scoped_template_context` configuration option remain only
for backwards compatibility and diagnostics.

This guide therefore focuses on helping you understand the semantics and, if you
are maintaining legacy providers or writing tests, how to opt into and verify
the (largely implicit) migration state. The overall goal remains the same: make
each provider self-contained so its templates do not accidentally depend on
values from elsewhere in your project.

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
4. (Optional) add `provider_migrated = True` at top-level in the provider's
   `repolish.py` if you want to make the migration state explicit for tests or
   debugging; it has no effect on rendering correctness.
5. Add/adjust unit tests for the provider to assert provider-scoped rendering
   behaviour (see test suggestions below).
6. The configuration flag and default behaviour already yield provider-scoped
   rendering. Run `poe ci-checks` / CI to detect any templates that
   inadvertently depend on other providers. The staging step records which
   provider supplied each template so that context isolation happens
   automatically.

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
from repolish import TemplateMapping
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
from repolish.loader import Provider, TemplateMapping, FileMode

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

  Only one subclass may be exported; the old behaviour chose the first class
  encountered which could hide accidental imports of helper providers. The
  loader now looks at the module's `__all__` list (if present) and will use the
  single provider class named there. This lets you freely import other provider
  implementations at the top level so long as only the intended class is
  included in `__all__`. Exporting multiple providers either via `__all__` or by
  omitting `__all__` still results in a runtime error with a helpful message
  directing you to the `__all__` mechanism.

- If a provider class is selected, the loader instantiates it and _injects_
  instance-backed callables into the module dict (e.g. `create_context`,
  `create_file_mappings`, `create_anchors`) so the rest of the loader works
  exactly the same as with module-style providers (see
  `repolish.loader.orchestrator._inject_provider_instance`).

Practical notes

- You do not need to set `provider_migrated = True` for rendering isolation;
  every provider already has its own context. the flag can be useful in tests or
  when debugging older providers, but its presence or absence has no effect on
  template output.
- The class-based API is optional but recommended for larger providers and when
  you want compile/test-time reassurance (Pydantic types give IDE + validation
  benefits).
- Existing module-style providers continue to work with no changes; just avoid
  relying on cross-provider context to make future maintenance easier.

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
  1. Migrate provider code incrementally; adding `provider_migrated = True` is
     only needed for local tests or diagnostics, not for correctness.
  2. Run CI (provider-scoped rendering is already the default) in a feature
     branch.
  3. Fix templates that fail; repeat until the branch is green.
  4. Merge once providers are behaving as desired; there is no extra flag to
     flip in the mainline.

Commands & quick checks

- Run unit/tests: `poe ci-checks` or `pytest -q`
- Verify provider flags: inspect `Providers.provider_migrated` in the loader
  output or add a unit test asserting the flag is present.

Final notes

- Provider-scoped rendering is now the default; you don't need to opt in or flip
  any configuration flags. The previous `provider_scoped_template_context`
  option and the `provider_migrated` flag will eventually be removed, but they
  currently remain for backwards compatibility and unit tests.
- Having a `provider_migrated = True` declaration in a provider is mostly a
  convenience for tooling and logging. It does not change how templates are
  rendered.
- If you want, I can update the example providers in `examples/` to show a full
  end‑to‑end migrated provider (the examples already work without any changes).
