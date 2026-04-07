# Providers

A provider is a self-contained unit that ships templates, context, and
behaviour. Repolish assembles the final project state by loading all registered
providers in order and merging their contributions.

## What a provider contributes

| Contribution    | How it is declared                                       |
| --------------- | -------------------------------------------------------- |
| Templates       | Files under `templates/repolish/`                        |
| Context values  | `create_context()`      |
| Anchor content  | `create_anchors()` — replacement strings for templates   |
| File mappings   | `create_file_mappings()` — conditional / delete / create-only |
| Delete requests | `TemplateMapping(None, None, FileMode.DELETE)` in mappings |
| Symlinks        | `create_default_symlinks()` or the `symlinks:` config key |

## Writing a provider

A provider is a Python package with a `repolish.py` that contains a `Provider`
subclass. Subclass `repolish.Provider` and supply a typed Pydantic context:

```
my-provider/
├── repolish.py
└── templates/
    └── repolish/
        ├── Makefile
        └── .github/
            └── workflows/
                └── ci.yml
```

`repolish.py`:

```python
from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    python_version: str = '3.11'


class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_anchors(self, context: Ctx) -> dict[str, str]:
        return {'install-extras': 'pip install -e ".[dev]"'}
```

`create_context()` is the only required method.
All others have default no-op implementations.

## How providers are loaded

1. Repolish resolves each `providers:` entry in `repolish.yaml` to a local
   directory (via `provider_root`, `cli`, or `.repolish/_/provider-info.*.json`).
2. Each directory is scanned for a `repolish.py` containing a `Provider` subclass.
3. Providers are loaded in config order. Later providers can read earlier
   providers' context in their own `create_context()` calls.
4. All contributions (context, anchors, mappings) are merged into a single
   `Providers` bundle before staging begins.

## Monorepo mode handlers

When the same provider needs different behaviour in a monorepo root vs a package
member, attach `ModeHandler` subclasses to the provider class instead of writing
`if mode == ...` branches. See the [Mode Handlers guide](../guides/mode-handler.md)
for details.
