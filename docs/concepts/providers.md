# Providers

A provider is a self-contained unit that ships templates, context, and
behaviour. Repolish assembles the final project state by loading all registered
providers in order and merging their contributions.

## What a provider contributes

| Contribution    | How it is declared                                            |
| --------------- | ------------------------------------------------------------- |
| Templates       | Files under `templates/repolish/`                             |
| Context values  | `create_context()`                                            |
| Anchor content  | `create_anchors()` — replacement strings for templates        |
| File mappings   | `create_file_mappings()` — conditional / delete / create-only |
| Delete requests | `TemplateMapping(None, None, FileMode.DELETE)` in mappings    |
| Symlinks        | `create_default_symlinks()` or the `symlinks:` config key     |

### Resources and symlinks

Templates are not the only thing a provider ships. A provider package can also
carry static resources — configuration files, scripts, schemas — that tools in
your project need to read directly from disk.

When a user runs `repolish link`, those resources land at:

```
.repolish/<provider-name>/ruff.toml
.repolish/<provider-name>/scripts/check.sh
```

This is the same idea as `node_modules/eslint-config-my-org/index.js`: the
configuration lives right next to the project, at a short, stable path, without
having to dig through `.venv/lib/python3.x/site-packages/...`. Tools that read
config files — linters, formatters, task runners — can point straight at
`.repolish/<provider-name>/ruff.toml` and just work.

For tools that expect config at the project root, the `symlinks:` key in
`repolish.yaml` (or `create_default_symlinks()` in code) surfaces those files
where they need to be:

```yaml
providers:
  myprovider:
    cli: myprovider-link
    symlinks:
      - source: ruff.toml
        target: ruff.toml
```

The file lives once under `.repolish/`. The symlink makes it appear at the root.
Every project that links to the same provider stays in sync automatically the
next time the provider is updated.

Symlinks at the project root should normally be added to `.gitignore`. The
symlinks are absolute paths on the machine that ran `repolish link`, so they are
not portable across clones. Anyone who checks out the repo runs `repolish link`
once to recreate them.

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

`create_context()` is the only required method. All others have default no-op
implementations.

## How providers are loaded

1. Repolish resolves each `providers:` entry in `repolish.yaml` to a local
   directory (via `provider_root`, `cli`, or
   `.repolish/_/provider-info.*.json`).
2. Each directory is scanned for a `repolish.py` containing a `Provider`
   subclass.
3. Providers are loaded in config order. Later providers can read earlier
   providers' context in their own `create_context()` calls.
4. All contributions (context, anchors, mappings) are merged into a single
   `Providers` bundle before staging begins.

## Monorepo mode handlers

When the same provider needs different behaviour in a monorepo root vs a package
member, attach `ModeHandler` subclasses to the provider class instead of writing
`if mode == ...` branches. See the
[Mode Handlers guide](../provider-development/mode-handler.md) for details.
