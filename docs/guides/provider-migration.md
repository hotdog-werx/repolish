# Migrating providers to v1

This guide covers the two changes required to bring a pre-v1 provider up to
date: switching from module-style functions to a class-based `Provider`, and
updating templates to use plain Jinja2 variable names instead of the old
`cookiecutter` namespace.

## 1. Module-style functions → class-based Provider

Old providers exposed bare module-level functions. The v1 API uses a typed
`Provider` subclass instead.

**Before:**

```python
# repolish.py (old module-style)
def create_context():
    return {'shared_prefix': 'lib'}

def create_file_mappings(ctx):
    return {'src/a.py': 'templates/mod.jinja'}
```

**After:**

```python
# repolish.py (v1 class-based)
from repolish import BaseContext, BaseInputs, FileMode, Provider, TemplateMapping


class Ctx(BaseContext):
    shared_prefix: str = 'lib'
    license: str = 'MIT'


class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_mappings(self, context: Ctx):
        return {
            'src/a.py': TemplateMapping('pkg_init.jinja', None),
            'README.md': TemplateMapping('readme.jinja', None, file_mode=FileMode.CREATE_ONLY),
        }
```

Use `BaseContext` (not a plain `BaseModel`) so the provider gets the built-in
`repolish` namespace (`repolish.repo.owner`, `repolish.year`, etc.) without
any extra fields.

Each `repolish.py` must contain exactly one `Provider` subclass. The loader
will find it automatically. If you import another provider class (e.g. a shared
base) at module level, declare `__all__` listing only the intended class so the
loader knows which one to use.

## 2. Template namespace: drop `cookiecutter.`

Old templates accessed context values through a `cookiecutter` wrapper object:

```jinja
{{ cookiecutter.shared_prefix }}
{{ cookiecutter.my_provider.api_url }}
```

In v1 the context keys are top-level Jinja2 variables — there is no
`cookiecutter` wrapper:

```jinja
{{ shared_prefix }}
{{ my_provider.api_url }}
```

Rename every `cookiecutter.` reference across your template files. To catch
stragglers, run `repolish lint` after updating — it reports any undefined
variable references in your templates.

## Troubleshooting

**Template references a key from another provider:** move the value into this
provider's `create_context()`, or pass it via `TemplateMapping(...,
extra_context=...)`, or keep the template under the provider that owns the
context.

**Multiple Provider subclasses in one module:** define `__all__` listing only
the intended class. The loader raises a clear error if it finds more than one
and `__all__` is absent.
