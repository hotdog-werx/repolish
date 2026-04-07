# Part 1 — Workspace Provider

Every project you work on needs the same foundation: a tool installer, a
formatter, and a task runner. You set these up by hand in every new repo, and
they drift within months. Let's fix that with a provider.

## The problem

You maintain several Python projects. Each one needs:

- `mise.toml` — installs `uv`, `dprint`, and `poethepoet`
- `poe_tasks.toml` — defines a `format` task that runs dprint
- `dprint.json` — dprint formatter configuration

Copy-pasting these files works for week one. By week four one project has an
older version of dprint pinned, another has a different formatter config, and
you have lost track of which is canonical. You need a single source of truth.

## Creating the provider package

A provider is a Python package. Start a new directory:

```
devkit-workspace/
├── pyproject.toml
└── devkit/
    └── workspace/
        ├── __init__.py
        ├── py.typed
        └── repolish/
            ├── __init__.py
            └── provider.py
        └── resources/
            └── templates/
                ├── repolish.py
                └── repolish/
                    ├── mise.toml.jinja
                    ├── dprint.json
                    └── poe_tasks.toml.jinja
```

`pyproject.toml` registers the provider's CLI entry point so repolish can
discover it:

```toml
[project]
name = "devkit-workspace"
version = "0.1.0"
dependencies = ["repolish"]

[project.scripts]
devkit-workspace-link = "repolish.linker:main"

[tool.repolish.provider]
templates_dir = "devkit/workspace/resources/templates"
```

## Defining the context

Create `devkit/workspace/repolish/provider.py`:

```python
from repolish import BaseContext, BaseInputs, Provider, override


class WorkspaceContext(BaseContext):
    dprint_version: str = '0.49.0'
    uv_version: str = '0.5.0'
    poe_version: str = '0.29.0'


class WorkspaceProvider(Provider[WorkspaceContext, BaseInputs]):
    @override
    def create_context(self) -> WorkspaceContext:
        return WorkspaceContext()
```

`BaseContext` gives you `ctx.repolish.repo.owner`, `ctx.repolish.repo.name`,
and the workspace mode automatically. Your own fields (`dprint_version`, etc.)
become available in every template.

Register it in `devkit/workspace/resources/templates/repolish.py`:

```python
from devkit.workspace.repolish.provider import WorkspaceProvider
__all__ = ['WorkspaceProvider']
```

## Writing the templates

### `mise.toml.jinja`

```toml
[settings]
experimental = true
python.uv_venv_auto = true

[tools]
uv = "{{ dprint_version }}"
dprint = "{{ dprint_version }}"
## repolish-multiregex-block[tools]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$

"pipx:poethepoet" = "{{ poe_version }}"

[tasks]
setup-hook.run = "mise exec -- poe setup-hook"

[hooks]
postinstall = ["mise run setup-hook"]
```

The `repolish-multiregex` directives let your projects pin specific tool
versions. On each apply the provider adds any new tools it ships while
preserving the versions you have already set.

### `poe_tasks.toml.jinja`

```toml
[tool.poe.tasks]
format.help = "run all formatters"
format.sequence = ["format-dprint"]

format-dprint.help = "run dprint"
format-dprint.cmd = "dprint fmt"
```

This is a plain Jinja template for now. The tasks are hardcoded. In
[Part 2](02-python-provider.md) you will discover you need other providers to
contribute tasks into this file, and that is what drives the next change.

### `dprint.json`

```json
{
  "$schema": "https://dprint.dev/schemas/v0.json",
  "includes": ["**/*.{json,toml,md}"],
  "excludes": [".repolish/**"],
  "plugins": [
    "https://plugins.dprint.dev/json-0.19.3.wasm",
    "https://plugins.dprint.dev/toml-0.6.2.wasm",
    "https://plugins.dprint.dev/markdown-0.17.2.wasm"
  ]
}
```

## Installing and applying

Install the provider in development mode:

```bash
uv pip install -e ./devkit-workspace
```

Link it to your project:

```bash
repolish link devkit-workspace
```

Create a minimal `repolish.yaml`:

```yaml
providers:
  workspace:
    cli: devkit-workspace-link
```

Apply:

```bash
repolish apply
```

Your project now has `mise.toml`, `poe_tasks.toml`, and `dprint.json` all
generated from the provider. Run the formatter:

```bash
mise run setup-hook   # installs tools
poe format
```

Every project that uses this provider will stay in sync as you update the
provider. Bump `dprint_version` in the provider, run `repolish apply` in each
project, and the version is updated everywhere — while preserving any local tool
pin overrides you set in individual projects.

---

Next: [Part 2 — Python Provider](02-python-provider.md)
