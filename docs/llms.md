# Repolish — AI Agent Reference

This page gives an AI assistant everything needed to answer questions about
repolish and help users configure, author, and debug it. Read this first, then
follow the links for deeper detail on any topic.

---

## Prerequisites — getting the tools

Before helping a user, confirm which tools they have. The recommended path is
**mise → uv → uvx**, which works on macOS, Linux, and Windows and requires no
system Python configuration.

### mise

[mise](https://mise.jdx.dev) is a polyglot tool manager — one config file, all
tools, all platforms. It handles Python, Node, Go, Rust, and more. Install it
once:

```bash
curl https://mise.run | sh
```

### Bootstrapping a new provider package

To scaffold a provider from scratch, all you need is a minimal `mise.toml` with
`uv`, then use `uvx` to run repolish without any further install:

```bash
mkdir my-provider && cd my-provider
cat > mise.toml << 'EOF'
[settings]
experimental = true
python.uv_venv_auto = true

[tools]
uv = "latest"
EOF
mise trust && mise install
uvx repolish scaffold . --package myorg.myprovider
```

### Setting up a consumer project

If the user is working on a project that will `uv sync` and wants project tools
on their PATH automatically, the `mise.toml` needs two extra settings:

```toml
[settings]
experimental = true
python.uv_venv_auto = true # auto-activates the uv venv on cd

[tools]
uv = "latest"
```

`python.uv_venv_auto` (requires `experimental = true`) tells mise to activate
the `uv`-managed virtualenv whenever you enter the directory. Without it,
`repolish` and other project tools installed via `uv add` won't be found on PATH
after `uv sync`.

Full walkthrough: [Installation](getting-started/installation.md) —
[Tutorial Part 1](tutorial/01-workspace-provider.md)

### Traditional install

If the user already has Python 3.11+ and prefers a direct install:

```bash
uv add repolish   # or: pip install repolish
```

---

## What repolish does

Repolish is a **template-push system with drift detection**. A team packages
their repository standards into one or more _providers_. Every project that opts
in via `repolish.yaml` can pull the latest standards with `repolish apply`, or
detect drift against them with `repolish --check`.

Key property: repolish never blindly overwrites the project. Preprocessor
directives capture local state (pinned versions, custom sections) before
rendering, so each apply merges the standard template with the project's own
values.

---

## Mental model

```
providers (packages)  →  templates + context + directives
                                      ↓
                           Jinja2 render with merged context
                                      ↓
                           Preprocessors capture local values
                                      ↓
                      write files  OR  report drift (--check)
```

Two CLI commands cover the main loop:

| Command                   | What it does                                                  |
| ------------------------- | ------------------------------------------------------------- |
| `repolish link`           | Registers providers; writes resources to `.repolish/<alias>/` |
| `repolish apply`          | Renders templates and writes files to the project             |
| `repolish apply --check`  | Same pipeline but reports drift without writing               |
| `repolish preview <file>` | Shows preprocessor output for one template (debugging)        |
| `repolish lint`           | Validates a provider's templates against its context model    |
| `repolish scaffold`       | Scaffolds a new provider package                              |

---

## repolish.yaml — the config file

Every project has a `repolish.yaml`. The most important keys:

```yaml
providers: # required
  my-provider: # alias (short name used everywhere)
    cli: my-provider-link # OR provider_root: ./local/
    symlinks: # symlinks created at project root
      - source: ruff.toml # path inside .repolish/my-provider/
        target: ruff.toml # path at project root
    context: # shallow-merge into this provider's context
      python_version: '3.12'
    context_overrides: # deep dot-notation patch into this provider's context
      tools.uv.version: '0.5.0'

paused_files: # repolish skips these entirely
  - .github/workflows/ci.yml

template_overrides: # pin a file to a specific provider
  pyproject.toml: other-provider # or null to suppress altogether
```

Full schema: [repolish.yaml Schema](provider-development/config-file.md)

---

## Context and how it merges

Templates are Jinja2. The context dictionary they receive is assembled in this
order (later wins):

1. **Global context** — `repolish.repo.owner`, `repolish.repo.name`,
   `repolish.year` — always present, no config needed.
2. **Provider `create_context()`** — each provider contributes its typed
   Pydantic model; providers run in config order, later providers can read
   earlier ones.
3. **`context:`** under a provider entry in `repolish.yaml` — shallow update;
   replaces top-level keys of that provider's context wholesale.
4. **`context_overrides:`** under a provider entry — deep dot-notation patch;
   targets a single nested field without touching the rest.

Use `context:` for simple scalar overrides. Use `context_overrides:` when the
provider exposes nested objects and you only want to change one field. Both are
per-provider — there is no top-level `context:` key.

Full detail: [Context](concepts/context.md)

---

## Providers — what they are and how to write one

**Always start a new provider with `repolish scaffold`**, not by hand. The
scaffold generates the complete package structure with all imports, entry
points, and wiring already in place. Trim what you do not need; do not start
from a blank file.

### Choosing a package name

The `--package` argument determines the file layout and import path. There are
two styles — ask the user which they prefer before running scaffold:

| Style         | Example `--package` | Import path                    | Directory layout               |
| ------------- | ------------------- | ------------------------------ | ------------------------------ |
| **Flat**      | `devkit_workspace`  | `import devkit_workspace`      | `devkit_workspace/repolish.py` |
| **Namespace** | `devkit.workspace`  | `from devkit import workspace` | `devkit/workspace/repolish.py` |

Namespace packages (`devkit.workspace`, `devkit.python`, …) are a good fit when
a team ships multiple sibling providers — they share the `devkit` top-level
namespace and install cleanly alongside each other. Flat packages
(`devkit_workspace`) are simpler if the provider stands alone.

```bash
# flat package
uvx repolish scaffold . --package devkit_workspace

# namespace package (recommended for sibling providers)
uvx repolish scaffold . --package devkit.workspace

# monorepo-aware namespace package
uvx repolish scaffold packages/myprovider --package myorg.myprovider --monorepo
```

The generated structure:

```
myorg-myprovider/
├── pyproject.toml          ← entry point + build system pre-wired
├── repolish.yaml
├── README.md
└── myorg/
    └── myprovider/
        ├── __init__.py
        ├── py.typed
        └── repolish/
            ├── __init__.py
            ├── linker.py   ← resource_linker_cli already set up
            ├── models.py   ← Ctx and Inputs stubs
            └── provider.py ← Provider subclass with all hooks stubbed
        └── resources/
            ├── configs/
            └── templates/
                └── repolish/    ← templates go here
```

`pyproject.toml` already has the link CLI entry point registered:

```toml
[project.scripts]
myorg-myprovider-link = "myorg.myprovider.repolish.linker:main"
```

When writing provider logic from scratch (e.g. in a local provider without its
own package), the minimal `repolish.py` is:

```python
from repolish import BaseContext, BaseInputs, Provider, TemplateMapping, FileMode

class Ctx(BaseContext):
    python_version: str = '3.11'

class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_anchors(self, context: Ctx) -> dict[str, str]:
        return {'install-cmd': 'uv sync'}

    def create_file_mappings(self, context: Ctx) -> dict[str, TemplateMapping]:
        return {}

    def promote_file_mappings(self, context: Ctx) -> dict[str, TemplateMapping]:
        # member mode only: paths resolve relative to the monorepo root
        return {}

    def create_default_symlinks(self) -> list:
        return []
```

All public types import from `repolish` directly:

```python
from repolish import (
    BaseContext, BaseInputs, FileMode, FinalizeContextOptions,
    ModeHandler, Provider, Symlink, TemplateMapping,
    call_provider_method, get_provider_context,
)
```

Templates live in `templates/repolish/` inside the provider package. The path
structure mirrors where the files will land in the project.

Full reference: [Provider Python API](provider-development/context.md)

---

## Linking — resources on disk

`repolish link` (or the provider's own `myprovider-link` CLI) copies/symlinks
the provider's resource directory to `.repolish/<alias>/`. This is the Python
equivalent of `node_modules/my-lib/config.yaml` — the config lives right next to
the project, at a short stable path, without digging through
`.venv/lib/python3.x/site-packages/...`.

```
.repolish/my-provider/ruff.toml      ← tool points here
.repolish/my-provider/scripts/       ← scripts accessible locally
```

Optional: surface a file at the project root with `symlinks:` in
`repolish.yaml`. Root symlinks are **absolute paths** so they should be
gitignored. Anyone who clones the repo runs `repolish link` once to recreate
them.

Full detail: [Resource Linker](provider-development/linker.md)

---

## Developer controls — what project owners can do

When a provider update breaks something or ships a change the user is not ready
for, these escape hatches apply (all configured in `repolish.yaml`):

| Escape hatch                    | Use when                                                                  |
| ------------------------------- | ------------------------------------------------------------------------- |
| `paused_files`                  | Skip a file entirely for now                                              |
| `template_overrides`            | Pin a file to a different provider, or `null` to delete it                |
| `context` / `context_overrides` | A template value is wrong for this project — set under the provider entry |
| `provider_root: ./local/`       | Replace an entire provider with a local copy                              |
| Anchors in files                | Protect a block of text from ever being overwritten                       |

Quick fix for "provider broke `ci.yml` and I need to ship":

```yaml
paused_files:
  - .github/workflows/ci.yml
```

Full reference: [Project Controls](project-controls/index.md)

---

## Anchors — protecting local edits inline

Anchors let users mark a block in a file that repolish must never overwrite,
even when the surrounding template changes:

```yaml
# repolish-anchor[my-section]: start
... user-owned content ...
# repolish-anchor[my-section]: end
```

The provider registers anchor names in `create_anchors()`. If the project has
placed content under that anchor name, repolish substitutes the user's content
at render time instead of the provider default.

Full detail: [Preserve Your Edits](project-controls/anchors.md)

---

## Preprocessors — capturing local state

Preprocessor directives are inline markers inside template files. They read a
value from the existing project file before overwriting it, then inject that
value back into the rendered output. This is how versions, pinned config values,
and custom sections survive every apply.

Example — capture the current Python version from the project's existing file:

```
# repolish-multiregex-block[python-version]: ^python_requires\s*=\s*"(.*?)"
```

Full detail: [Preprocessors](concepts/preprocessors.md)

---

## Monorepo support

Set `workspace:` in the root `repolish.yaml`. Repolish discovers members from
`[tool.uv.workspace]` in `pyproject.toml` (or list them explicitly under
`workspace.members`). It runs a dry provider pass for each member, then a full
pass for root and each member separately.

Providers receive `context.repolish.workspace.mode` — `"root"`, `"member"`, or
`"standalone"`. Use `ModeHandler` subclasses to attach mode-specific behaviour
without `if mode == ...` branches.

Full detail: [Monorepo](concepts/monorepo.md)

---

## Common tasks and where to look

| User says                                    | Where to point them                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------------------- |
| "I want to get started"                      | [Quick Start](getting-started/quick-start.md)                                          |
| "CI is failing with exit 2"                  | `repolish --check` found drift; run `repolish apply` locally                           |
| "How do I skip a file?"                      | `paused_files` — [Pause a File](project-controls/pause.md)                             |
| "A template value is wrong for my project"   | `context_overrides` — [Override Context](project-controls/context-overrides.md)        |
| "I want to write a provider"                 | Run `repolish scaffold` first — [Provider Python API](provider-development/context.md) |
| "I want to share a config file across repos" | Linking — [Resource Linker](provider-development/linker.md)                            |
| "I want to protect a block in a file"        | [Preserve Your Edits](project-controls/anchors.md)                                     |
| "I need this to work in a monorepo"          | [Monorepo Setup](provider-development/monorepo.md)                                     |
| "We migrated from an older provider style"   | [Provider Migration](provider-development/provider-migration.md)                       |
| "I want to preview preprocessor output"      | `repolish preview <template-file>` — [preview](reference/preview.md)                   |

---

## What repolish does NOT do

- It does not run in a daemon or watch mode — it is a one-shot CLI.
- It does not manage Python environments or install packages.
- It does not resolve merge conflicts — pausing the file is the escape hatch.
- Templates are pure Jinja2 with `StrictUndefined` — undefined variables are
  errors, not empty strings.
- There is no cookiecutter integration in v1; the old `{{ cookiecutter.x }}`
  namespace is gone.

---

## Testing providers

The `repolish.testing` module gives provider authors a lightweight harness for
exercising every provider hook without the full CLI pipeline, git repos, or
installed wheels.

```python
from repolish.testing import ProviderTestBed, assert_snapshots, make_context
```

### Quick start

```python
from repolish.testing import ProviderTestBed
from my_provider.repolish.provider import MyProvider

bed = ProviderTestBed(MyProvider)
ctx = bed.resolved_context
fm  = bed.file_mappings()         # dict[str, str | TemplateMapping | None]
anchors = bed.anchors()           # dict[str, str]
rendered = bed.render_all()       # dict[dest_path, rendered_content]
```

### Key helpers

| Helper                                 | Purpose                                                             |
| -------------------------------------- | ------------------------------------------------------------------- |
| `ProviderTestBed(ProviderClass)`       | Wraps a provider, calls `create_context()`, exposes lifecycle hooks |
| `bed.render('template.jinja')`         | Render a single template with the provider's context                |
| `bed.render_all()`                     | Render all mapped + auto-discovered templates                       |
| `assert_snapshots(rendered, snap_dir)` | Compare rendered output against golden files; unified diff on fail  |
| `make_context(mode=..., alias=...)`    | Factory for synthetic `RepolishContext` objects                     |

### Testing mode handlers and inputs

```python
# mode-specific behavior
bed_root   = ProviderTestBed(MyProvider, mode='root')
bed_member = ProviderTestBed(MyProvider, mode='member')

# cross-provider input exchange
inputs = bed.provide_inputs()
result = bed.finalize(received_inputs=[SomeInputs(flag=True)])
```

Full reference: [Testing Providers](provider-development/testing.md)
