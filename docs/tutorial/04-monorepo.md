# Part 4 — Going Monorepo

Moving the two providers into a single repository solves the sync problem and
enables something better: you can use repolish to manage the provider repo
itself.

> **Note:** This part is conceptual. It explains the monorepo structure and the
> patterns you will apply, but does not walk you through every command step by
> step. At the end there is an explicit checklist of what you need to do in the
> actual repository.

## The new layout

```
devkit/                         ← the providers monorepo
├── repolish.yaml               ← repolish config for the devkit repo itself
├── mise.toml                   ← managed by the workspace provider
├── poe_tasks.toml              ← managed by the workspace provider
├── dprint.json                 ← managed by the workspace provider
├── pyproject.toml              ← uv workspace root
└── packages/
    ├── workspace/              ← devkit-workspace package
    │   ├── pyproject.toml
    │   └── devkit/workspace/
    │       └── ...
    └── python/                 ← devkit-python package
        ├── pyproject.toml
        └── devkit/python/
            └── ...
```

Both packages are members of a `uv` workspace. They share a lock file, share
tooling, and can import each other during development without any extra
installation steps.

Before anything else, create a `mise.toml` at the repo root so that mise can
set up the Python environment and auto-activate the `.venv` that `uv` creates:

```toml
[settings]
experimental = true
python.uv_venv_auto = true

[tools]
uv = "latest"
```

Run `mise trust && mise install` after creating this file. This is the same
bootstrap step used in Part 1 — the devkit repo needs its own environment just
like any consumer project does.

Note that this `mise.toml` is a bootstrap file you create manually. The
workspace provider will later overwrite it with its managed version when you run
`repolish apply`, so make sure the provider's `mise.toml.jinja` template
includes the `[settings]` block too.

The root `pyproject.toml` declares the workspace and shared dev dependencies —
it is not a package itself:

```toml
[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = [
  "pytest>=8",
  "ruff>=0.9",
]
```

Create this file at the repo root before running any `uv` commands. It tells
`uv` that `packages/workspace` and `packages/python` are workspace members,
so a single `uv lock` at the root resolves all dependencies together.

## Scaffolding inside the monorepo

The two providers you built in Parts 1 and 2 handle a single deployment mode
(`standalone`). Inside a monorepo a provider can be invoked three ways:

- **root** — running against the repo root (assembles contributions from all
  members)
- **member** — running against one member package
- **standalone** — the classic single-project case

Re-scaffold each package with `--monorepo` to get the split structure:

```bash
mkdir devkit && cd devkit
git init

# workspace provider
uvx repolish scaffold packages/workspace --package devkit.workspace --monorepo

# python provider
uvx repolish scaffold packages/python --package devkit.python --monorepo
```

Each package now has a `provider/` sub-package instead of a flat `provider.py`:

```
packages/workspace/devkit/workspace/repolish/
├── __init__.py
├── linker.py
├── models.py
└── provider/
    ├── __init__.py   ← WorkspaceProvider class + root_mode/member_mode attrs
    ├── root.py       ← RootHandler
    ├── member.py     ← MemberHandler
    └── standalone.py ← StandaloneHandler
```

**What you need to do:**

> **Important:** The scaffold generates empty stubs — every `create_file_mappings`,
> `provide_inputs`, and `finalize_context` returns `{}` or `[]` by default.
> You must fill them in with the actual logic described in the "Final provider
> shapes" section below. The mapping values must also omit the `.jinja`
> extension: repolish strips it during staging, so `'_repolish.mise.toml'` is
> correct, not `'_repolish.mise.toml.jinja'`.

1. Create `packages/workspace/` and `packages/python/` and run the scaffold
   commands above.
2. Copy your existing `resources/templates/` files from `devkit-workspace` into
   `packages/workspace/devkit/workspace/resources/templates/`, **renaming each
   template with a `_repolish.` prefix** (e.g. `mise.toml.jinja` →
   `_repolish.mise.toml.jinja`).
3. Copy your existing `resources/configs/` files similarly (no renaming needed —
   configs are referenced as symlinks, not discovered automatically).
4. Copy the contents of `models.py` from each old repo into the corresponding
   `models.py` in the new package.
5. The provider logic (handlers, `provide_inputs`, `finalize_context`) goes
   into the appropriate `root.py`, `member.py`, and `standalone.py` files
   described below.

> **Why `_repolish.*`?** Any template file whose name starts with `_repolish.`
> is excluded from automatic discovery. Repolish will only render it when a
> handler's `create_file_mappings` explicitly references it by name. Without the
> prefix, every template in the `templates/` directory would be rendered in
> every mode regardless of which handler is active. With the prefix, each
> handler controls exactly what gets written and where.

The `provider/__init__.py` wires up the three handlers; the
rest of this part explains what to put in each one.

## Self-applying providers

The first thing that happens when you set this up is something pleasing: the
`devkit` repo itself becomes a consumer of its own workspace provider.

### Updating package dependencies

Before running anything, update each package's `pyproject.toml` so they agree
on the same version of `repolish` and so `devkit-python` can import from
`devkit-workspace` without a git URL.

In `packages/workspace/pyproject.toml`:

```toml
[project]
name = "devkit-workspace"
version = "0.2.0"
dependencies = [
    "repolish>=0.1.0",
]
```

In `packages/python/pyproject.toml`, declare the intra-workspace dependency
using `{ workspace = true }` instead of a git URL:

```toml
[project]
name = "devkit-python"
version = "0.1.0"
dependencies = [
    "repolish>=0.1.0",
    "devkit-workspace",
]

[tool.uv.sources]
devkit-workspace = { workspace = true }
```

`{ workspace = true }` tells `uv` to resolve `devkit-workspace` from the local
workspace member rather than PyPI or a git remote. No version pinning, no
publish cycle — changes in `devkit-workspace` are immediately visible to
`devkit-python`.

After updating both files, run from the repo root:

```bash
uv lock -U && uv sync
```

This regenerates the shared lock file and installs all packages, making both
CLIs (`devkit-workspace-link` and `devkit-python-link`) available in the
environment.

### The repolish.yaml

Because both packages are members of the same `uv` workspace, both CLIs are
installed and available just like they would be in any consumer project. The
`repolish.yaml` at the repo root uses the same `cli:` syntax:

```yaml
# repolish.yaml (in the devkit repo root)
providers:
  workspace:
    cli: devkit-workspace-link
```

The Python provider adds ruff tasks, but the devkit repo itself is a tooling
library rather than a Python application — so only the workspace provider is
wired in at the root. Run `repolish apply` and the workspace provider generates
`mise.toml` and `poe_tasks.toml` for the devkit repo itself.

This feedback loop is immediate. Edit a template, run `repolish apply`, see the
result. Fix it, apply again.

## Testing providers together

Because both packages live in the same repo, you can write integration tests
that load both providers in a single `create_providers()` call:

```python
from repolish.loader import create_providers


def test_python_provider_contributes_tasks(tmp_path):
    providers = create_providers([
        str(workspace_resources_dir),
        str(python_resources_dir),
    ])

    # Workspace provider should have received the ruff tasks block
    ctx = providers.provider_contexts['devkit-workspace']
    assert any('check-ruff' in block for block in ctx.extra_poe_tasks)
```

No publishing. No version coordination. No install-from-git hacks. Both
providers are on disk and the test runs in milliseconds.

## Sessions and mode awareness

When you run `repolish apply` at the monorepo root, repolish doesn't just run
once. It runs separately for each place that has a `repolish.yaml`:

- Once for the root itself
- Once for each member package that has its own `repolish.yaml`

Each of these runs is a **session** — a group of providers loaded and executed
together. Member sessions run first. The root session runs last, and it can see
what every member session contributed.

### Two context objects

Every provider has access to two related but distinct objects:

**`repolish.workspace`** — the global monorepo topology, identical for all
providers in a session:

```python
ctx.repolish.workspace.mode        # 'root', 'member', or 'standalone'
ctx.repolish.workspace.root_dir    # absolute path to the monorepo root
ctx.repolish.workspace.members     # list of all member packages
```

**`repolish.provider.session`** — this specific run's identity:

```python
ctx.repolish.provider.session.mode         # same as workspace.mode
ctx.repolish.provider.session.member_name  # e.g. 'devkit-workspace'
ctx.repolish.provider.session.member_path  # e.g. 'packages/workspace'
```

The difference matters when a single provider is present in multiple sessions.
`repolish.workspace` tells you about the repository as a whole.
`repolish.provider.session` tells you exactly which part of the repo _this
particular run_ is targeting.

### The `mise.toml` problem

`mise.toml` installs tools for the whole repo. It belongs at the root, not
inside every package. But the workspace provider managed it in Part 1 — so when
it runs as a member session inside `packages/workspace/`, it would write
`packages/workspace/mise.toml`, which is wrong.

The naive fix is to check the session mode in `create_file_mappings()` and
return `None` for files that don't belong at the current level:

```python
from repolish import TemplateMapping, override


class WorkspaceProvider(Provider[WorkspaceContext, WorkspaceInputs]):
    @override
    def create_file_mappings(self, context: WorkspaceContext) -> dict[str, str | TemplateMapping | None]:
        mode = context.repolish.provider.session.mode
        return {
            'mise.toml': '_repolish.mise.toml' if mode != 'member' else None,
            'poe_tasks.toml': '_repolish.poe_tasks.toml',
        }
```

Returning `None` for a path tells repolish to skip that file entirely for this
session. Members get their own `poe_tasks.toml` (containing only their own
tasks), but `mise.toml` only appears at the root. `dprint.json` is a config
file delivered via symlink, not a template, so it is not listed in mappings.

> **Don't do this in practice.** Once `provide_inputs`, `finalize_context`, and
> `create_context` also diverge by mode, this single-function approach becomes
> a wall of conditionals. That is exactly what `ModeHandler` was designed to
> avoid — see the next section.

### Cross-session inputs: members talk to root

Member sessions run first. Each member's `provide_inputs` can emit payloads —
and those payloads are forwarded to the root session's providers. The root
session's `finalize_context` sees inputs from **all** member sessions combined.

This is the mechanism that makes aggregation possible. A member says "here are
my tasks" by emitting a `WorkspaceInputs` payload. The root's workspace provider
collects them all in `finalize_context` and renders a single `poe_tasks.toml`
that contains every member's contribution.

Within a session, inputs flow in load order (provider A → provider B). Across
sessions, member inputs flow to root. Members cannot see each other's inputs and
cannot see root session inputs — the boundary is one-directional.

The session identity fields make this useful:

```python
# In WorkspaceProvider.provide_inputs (running as a member session):
member_name = opt.own_context.repolish.provider.session.member_name
member_path = opt.own_context.repolish.provider.session.member_path

return [WorkspaceInputs(
    poe_tasks_block=f'# tasks for {member_name}\n...',
    member_path=member_path,  # root uses this to know where the tasks came from
)]
```

### Using `ModeHandler` for cleaner separation

When root and member behaviour diverge across multiple methods, a `ModeHandler`
subclass keeps each case readable without branching inside every method:

```python
from repolish import ModeHandler, override


class RootHandler(ModeHandler[WorkspaceContext, WorkspaceInputs]):
    @override
    def create_file_mappings(self, context: WorkspaceContext):
        return {
            'mise.toml': '_repolish.mise.toml',
            'poe_tasks.toml': '_repolish.poe_tasks.toml',
        }


class MemberHandler(ModeHandler[WorkspaceContext, WorkspaceInputs]):
    @override
    def create_file_mappings(self, context: WorkspaceContext):
        return {
            'poe_tasks.toml': '_repolish.poe_tasks.toml',
        }


class WorkspaceProvider(Provider[WorkspaceContext, WorkspaceInputs]):
    root_mode = RootHandler
    member_mode = MemberHandler
```

Repolish dispatches to the right handler automatically based on the workspace
mode. If a mode has no handler set (e.g. `standalone_mode` is not assigned), the
provider falls back to its own methods directly — the same as if no
`ModeHandler` were involved at all.

## What you gain

- **One lock file** — `uv lock` resolves both packages and all their shared
  dependencies together.
- **Atomic changes** — a commit that updates the workspace provider's input
  schema and the python provider's `provide_inputs` in the same PR is safe,
  reviewable, and bisectable.
- **Single CI pipeline** — one workflow runs all provider tests, including the
  integration tests that need both providers installed.
- **Self-managing** — `repolish apply` keeps the devkit repo's own tooling up to
  date from the same templates the providers ship to consumers.

## Final provider shapes

Here is the complete structure for both providers once the monorepo migration is
done. This is the target state — what you are building toward.

The devkit monorepo is both a provider repo and a consumer of itself (root +
member sessions). `my-project` is an external standalone consumer.

### `devkit-workspace`

```python
# packages/workspace/devkit/workspace/repolish/provider/__init__.py
from repolish import Provider

from devkit.workspace.repolish.models import (
    WorkspaceProviderContext,
    WorkspaceProviderInputs,
)
from devkit.workspace.repolish.provider.member import WorkspaceMemberHandler
from devkit.workspace.repolish.provider.root import WorkspaceRootHandler
from devkit.workspace.repolish.provider.standalone import WorkspaceStandaloneHandler


class WorkspaceProvider(Provider[WorkspaceProviderContext, WorkspaceProviderInputs]):
    """WorkspaceProvider repolish provider."""

    root_mode = WorkspaceRootHandler
    member_mode = WorkspaceMemberHandler
    standalone_mode = WorkspaceStandaloneHandler
```

```python
# root.py — runs at the devkit repo root
class WorkspaceRootHandler(ModeHandler[WorkspaceProviderContext, WorkspaceProviderInputs]):
    @override
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[WorkspaceProviderContext],
    ) -> list[BaseInputs]:
        """Broadcast data to other providers from a root workspace."""
        tasks = '''\
format.help = "run all formatters"
format.sequence = ["format-dprint"]

format-dprint.help = "run dprint"
format-dprint.cmd = "dprint fmt --config .repolish/devkit-workspace/configs/dprint.json"
'''
        return [WorkspaceProviderInputs(poe_tasks_block=tasks)]

    @override
    def finalize_context(
        self,
        opt: FinalizeContextOptions[WorkspaceProviderContext, WorkspaceProviderInputs],
    ) -> WorkspaceProviderContext:
        """Merge inputs received from other providers (root workspace)."""
        blocks = [
            inp.poe_tasks_block
            for inp in opt.received_inputs
            if inp.poe_tasks_block
        ]
        opt.own_context.extra_poe_tasks = blocks
        return opt.own_context

    @override
    def create_file_mappings(
        self,
        context: WorkspaceProviderContext,
    ) -> dict[str, str | TemplateMapping | None]:
        """Map destination paths to template sources for root workspaces.

        Use ``self.templates_root`` to discover mode-specific templates under
        the provider's ``root/`` directory, e.g.::

            list(self.templates_root.glob('.github/workflows/*.yaml'))
        """
        return {
            'mise.toml': '_repolish.mise.toml',
            'poe_tasks.toml': '_repolish.poe_tasks.toml',
        }
```

```python
# member.py — runs inside packages/workspace/ and packages/python/
class WorkspaceMemberHandler(ModeHandler[WorkspaceProviderContext, WorkspaceProviderInputs]):
    def create_file_mappings(self, context):
        # no mise.toml at the member level
        return {'poe_tasks.toml': '_repolish.poe_tasks.toml'}

    def provide_inputs(self, opt):
        return []
```

```python
# standalone.py — runs in my-project (the classic case from Parts 1–2)
class WorkspaceStandaloneHandler(ModeHandler[WorkspaceProviderContext, WorkspaceProviderInputs]):
    def create_file_mappings(self, context):
        return {
            'mise.toml': '_repolish.mise.toml',
            'poe_tasks.toml': '_repolish.poe_tasks.toml',
        }

    def provide_inputs(self, opt):
        tasks = '''\
format.help = "run all formatters"
format.sequence = ["format-dprint"]

format-dprint.help = "run dprint"
format-dprint.cmd = "dprint fmt --config .repolish/devkit-workspace/configs/dprint.json"
'''
        return [WorkspaceProviderInputs(poe_tasks_block=tasks)]

    def finalize_context(self, opt):
        blocks = [
            inp.poe_tasks_block
            for inp in opt.received_inputs
            if inp.poe_tasks_block
        ]
        opt.own_context.extra_poe_tasks = blocks
        return opt.own_context
```

### `devkit-python`

The Python provider has no file mappings of its own — it only emits inputs.
All three modes do the same thing, so `StandaloneHandler` covers the
`my-project` case and the flat `provider.py` from Part 2 can be reused as-is
for standalone. In the monorepo, the member handler emits ruff tasks upward to
the root session:

```python
# member.py
class PythonMemberHandler(ModeHandler[PythonProviderContext, PythonProviderInputs]):
    def provide_inputs(self, opt):
        tasks = '''\
check-ruff.help = "run ruff linter and formatter check"
check-ruff.cmd = "uvx ruff check ."
'''
        return [WorkspaceProviderInputs(poe_tasks_block=tasks)]
```

The root session's `WorkspaceProvider.finalize_context` collects this along
with every other member's contribution and renders a unified `poe_tasks.toml`.

> **Simplification opportunity.** `WorkspaceRootHandler` and
> `WorkspaceStandaloneHandler` share identical `provide_inputs` and
> `finalize_context` logic. Once everything is working you can extract that
> into a shared helper module and import it from both — keeping each handler
> class thin. That refactor is left as an exercise for the reader.

## Checkpoint

**Concrete steps to complete before moving on:**

1. Create `mise.toml` at the repo root and run `mise trust && mise install`.
2. Create `pyproject.toml` at the repo root (uv workspace root, `package = false`).
3. Scaffold both packages with `--monorepo`.
4. Copy templates, configs, and models from the old separate repos.
5. Update `packages/workspace/pyproject.toml` and `packages/python/pyproject.toml`
   with matching `repolish` version floors and `devkit-workspace = { workspace = true }`.
6. Run `uv lock -U && uv sync` from the repo root.
7. Implement `RootHandler`, `MemberHandler`, and `StandaloneHandler` for each
   provider using the shapes above.
8. Add `repolish.yaml` at the root with `cli: devkit-workspace-link`.
9. Run `repolish apply` from the repo root and verify `mise.toml` and
   `poe_tasks.toml` are generated correctly.

Once everything is working, tag the monorepo:

```bash
git add -A && git commit -m "feat: initial devkit monorepo combining workspace and python providers"
git tag v1.0.0
```

---

Next: [Part 5 — Everything Together](05-using-all-providers.md)
