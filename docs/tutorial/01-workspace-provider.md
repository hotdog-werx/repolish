# Part 1 — Workspace Provider

Every project you work on needs the same foundation: a tool installer, a
formatter, and a task runner. You set these up by hand in every new repo, and
they drift within months. Let's fix that with a provider.

## Set up the consumer project

Before writing any provider code you need a project to apply it to. Create a git
repository called `my-project` — this is the repo that will receive templated
files throughout the tutorial:

```bash
mkdir my-project && cd my-project
git init
echo '# my-project' > README.md
git add README.md
git commit -m "chore: initial"
git tag initial
```

The `initial` tag marks the state of the project before repolish has touched
anything. You will return to this tag when comparing before and after.

`my-project` is a local sandbox for this tutorial — it does not need to be on
GitHub. The provider packages (`devkit-workspace`, `devkit-python`) are the
pieces that get published so other projects can consume them.

## The problem

You maintain several Python projects. Each one needs:

- `mise.toml` — installs `uv`, `dprint`, and `poethepoet`
- `poe_tasks.toml` — defines a `format` task that runs dprint
- `dprint.json` — dprint formatter configuration

Version drift across these files is not the real problem — tools like Renovate
or Dependabot handle that. The real problem is **configuration drift**: the
decisions baked into these files. Which dprint plugins does the project include?
What is the canonical `format` task sequence? Does `mise.toml` enable
`python.uv_venv_auto`? These are not references to an external source of truth —
they are committed text, duplicated across every repo, and there is no automated
tool that keeps them aligned.

When you settle on a better `mise.toml` structure after three months of
experience, you have to touch every repo by hand. Some get updated, some don't,
and six months later each repo has its own small variation that made sense to
someone at some point.

Not every variation is wrong, though. Some repos legitimately need different
plugin sets or task sequences. The goal is not uniformity — it is a single
source of truth that ships sensible defaults while leaving room for intentional
local differences.

## Creating the provider package

A provider is a Python package. Create a new directory for it and bootstrap it
with a package manager so `uv` is available:

=== "With mise"

    ```bash
    mkdir devkit-workspace && cd devkit-workspace
    cat > mise.toml << 'EOF'
    [settings]
    experimental = true
    python.uv_venv_auto = true

    [tools]
    uv = "latest"
    EOF
    mise trust && mise install
    ```

    `experimental = true` and `python.uv_venv_auto = true` tell mise to
    activate the `uv`-managed virtualenv automatically when you enter the
    directory. Without them, `repolish` and other project tools won't be on
    your PATH after `uv sync`.

=== "With uv already installed"

    ```bash
    mkdir devkit-workspace && cd devkit-workspace
    ```

    If you already have `uv` on your PATH (e.g. installed via `pip`,
    `pipx`, or your system package manager), no extra tooling file is needed.
    You can skip straight to scaffolding.

With `uv` available, use `uvx` to run `repolish scaffold` without installing
anything permanently:

```bash
uvx repolish scaffold . --package devkit.workspace
```

> **Note:** once repolish is published to PyPI `uvx repolish` will pull the
> latest release automatically. Until then, substitute the git URL and point it
> at any branch you want to use — `master` for the stable branch, or a feature
> branch to test a specific version:
>
> ```bash
> uvx --from "git+https://github.com/hotdog-werx/repolish.git@master" \
>     repolish scaffold . --package devkit.workspace
> ```

The scaffold creates 11 files:

```
devkit-workspace/
├── pyproject.toml
├── repolish.yaml
├── README.md
└── devkit/
    └── workspace/
        ├── __init__.py
        ├── py.typed
        └── repolish/
            ├── __init__.py
            ├── linker.py
            ├── models.py
            └── provider.py
        └── resources/
            ├── configs/
            │   └── .gitkeep
            └── templates/
                ├── repolish.py
                └── repolish/
                    └── .gitkeep
```

`pyproject.toml` is already wired up with the right entry point and build
backend:

```toml
[project]
name = "devkit-workspace"
version = "0.1.0"
dependencies = ["repolish"]

[project.scripts]
devkit-workspace-link = "devkit.workspace.repolish.linker:main"

[build-system]
requires = ["uv_build"]
build-backend = "uv_build"
```

> **Note:** `dependencies = ["repolish"]` pulls the latest PyPI release once
> repolish is published. Until then — or to track a specific branch — use the
> git URL directly:
>
> ```toml
> dependencies = [
>   "repolish @ git+https://github.com/hotdog-werx/repolish.git@master",
> ]
> ```

`models.py` is where the context and inputs classes live. `provider.py` is the
main `WorkspaceProvider` class. You will fill these in next.

Before opening any source files, create the lock file and virtual environment so
your IDE can resolve imports:

```bash
uv lock -U && uv sync
```

`uv lock -U` resolves and writes `uv.lock`; `uv sync` creates `.venv` and
installs all dependencies into it. After this step `repolish` appears in your
IDE's import completions and type checker.

## Defining the context

Open `devkit/workspace/repolish/models.py` and add the version fields your
templates will need:

```python
from repolish import BaseContext, BaseInputs


class WorkspaceProviderContext(BaseContext):
    dprint_version: str = '0.49.0'
    uv_version: str = '0.5.0'
    poe_version: str = '0.29.0'


class WorkspaceProviderInputs(BaseInputs):
    """Inputs for the WorkspaceProvider."""
```

`BaseContext` gives you `ctx.repolish.repo.owner`, `ctx.repolish.repo.name`, and
the workspace mode automatically. Your own fields (`dprint_version`, etc.)
become available in every template.

The scaffold already registered the provider in
`devkit/workspace/resources/templates/repolish.py` — no changes needed there.

## Writing the templates

> **Note:** The templates below are intentionally simplified. In a real provider
> you would likely use a more structured approach for `mise.toml` (e.g. a
> dedicated lockfile or a separate config management tool) and a more flexible
> task system. The goal here is to have just enough moving parts to show how
> repolish orchestrates communication between providers — not to prescribe a
> production-ready tooling setup.

Drop the template files into `devkit/workspace/resources/templates/repolish/`
(the scaffold left a `.gitkeep` placeholder there).

### `mise.toml.jinja`

```toml
[settings]
experimental = true
python.uv_venv_auto = true

## repolish-multiregex-block[tools]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
[tools]
uv = "{{ uv_version }}"
dprint = "{{ dprint_version }}"
"pipx:poethepoet" = "{{ poe_version }}"
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
format-dprint.cmd = "dprint fmt --config .repolish/devkit-workspace/configs/dprint.json"
```

The `--config` flag points dprint at the file repolish will symlink into the
consumer project — no `dprint.json` at the repo root needed. In
[Part 2](02-python-provider.md) you will discover you need other providers to
contribute tasks into this file, and that is what drives the next change.

### `configs/dprint.json`

Instead of rendering `dprint.json` as a template, ship it as a static config
file that repolish symlinks into every consumer project. Create
`devkit/workspace/resources/configs/dprint.json`:

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

After `repolish link devkit-workspace`, this file appears in the consumer at
`.repolish/devkit-workspace/configs/dprint.json` via a symlink. When you update
the config in the provider and consumers run `repolish apply`, the symlink
already points at the new version — nothing to regenerate.

## Publishing the provider to GitHub

Before you can install the provider in a real consumer project it needs to live
somewhere. First, initialize git in `devkit-workspace` if you haven't already:

```bash
git init
git add -A
git commit -m "feat: initial scaffold"
```

Create an empty repository on GitHub (no README, no `.gitignore`), then connect
and push:

```bash
git remote add origin git@github.com:your-org/devkit-workspace.git
git branch -M main
git push -u origin main
```

Now tag the initial release and push the tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

You can keep the repo public or private — the install command is the same either
way. For private repositories, `uv` reads the `GITHUB_TOKEN` environment
variable, so set it to a GitHub Personal Access Token with `repo` scope before
running any `uv add git+https://github.com/…` command.

With the repo at `github.com/your-org/devkit-workspace`, consumer projects
install directly from GitHub:

```bash
uv add git+https://github.com/your-org/devkit-workspace@v0.1.0
```

This pins to the `v0.1.0` tag you will create at the checkpoint. Whenever you
bump the version and push a new tag, consumers update by changing the ref —
exactly the same workflow as a PyPI package, but without the publish step.

## Installing and applying

From inside `my-project`, first give it a `mise.toml` so `uv` is available and a
minimal `pyproject.toml` so `uv add` has a project to work with:

```bash
cat > mise.toml << 'EOF'
[settings]
experimental = true
python.uv_venv_auto = true

[tools]
uv = "latest"
EOF
mise trust && mise install

cat > pyproject.toml << 'EOF'
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
EOF
uv lock
```

Then install the provider from GitHub:

```bash
uv add git+https://github.com/your-org/devkit-workspace@v0.1.0
```

> **Note:** the `@v0.1.0` ref can be a tag, branch, or commit SHA. During active
> development you can point at a branch to pick up changes without tagging:
>
> ```bash
> uv add git+https://github.com/your-org/devkit-workspace@main
> ```

Create a minimal `repolish.yaml`:

```yaml
providers:
  workspace:
    cli: devkit-workspace-link
```

The next step is optional since running `repolish apply` will automatically link
the provider if it hasn't been linked yet:

```bash
repolish link
```

Before applying, commit everything so you can see exactly what repolish changes:

```bash
git add -A && git commit -m "chore: add provider and tooling bootstrap"
```

Apply:

```bash
repolish apply
```

Your project now has `mise.toml` and `poe_tasks.toml` generated from the
provider, and `dprint.json` symlinked into `.repolish/devkit-workspace/configs/`
from the provider package. The new `mise.toml` includes `dprint` and
`poethepoet`, so install them before running any tasks:

```bash
mise install
```

Then run the formatter:

```bash
poe format
```

Every project that uses this provider will stay in sync as you update the
provider. Bump `dprint_version` in the provider, run `repolish apply` in each
project, and the version is updated everywhere — while preserving any local tool
pin overrides you set in individual projects.

## Checkpoint

Tag both repositories so you have a permanent reference for the state at the end
of Part 1.

In `devkit-workspace`, commit any remaining changes (templates, configs) and
push:

```bash
git add -A && git commit -m "feat: workspace provider v0.1.0"
git push origin main
```

The `v0.1.0` tag was already pushed when you published the provider above.

In `my-project`:

```bash
git add -A && git commit -m "chore: apply workspace provider"
git tag part-1
```

You can compare the `initial` and `part-1` tags to see everything that changed
during onboarding — the bootstrap files you created manually as well as the
files repolish generated:

```bash
git diff initial part-1
```

---

Next: [Part 2 — Python Provider](02-python-provider.md)
