# Part 4 — Going Monorepo

Moving the two providers into a single repository solves the sync problem and
enables something better: you can use repolish to manage the provider repo
itself.

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

## Self-applying providers

The first thing that happens when you set this up is something pleasing: the
`devkit` repo itself becomes a consumer of its own providers.

```yaml
# repolish.yaml (in the devkit repo root)
providers:
  workspace:
    provider_root: packages/workspace/devkit/workspace/resources
  python:
    provider_root: packages/python/devkit/python/resources
```

`provider_root` points directly at the provider's local resources directory.
No build, no install, no publish required. Run `repolish apply` and the
workspace provider generates `mise.toml` and `poe_tasks.toml` for the devkit
repo itself — including the ruff tasks contributed by the python provider.

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
together. Member sessions run first. The root session runs last, and it can
see what every member session contributed.

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
`repolish.provider.session` tells you exactly which part of the repo *this
particular run* is targeting.

### The `mise.toml` problem

`mise.toml` installs tools for the whole repo. It belongs at the root, not
inside every package. But the workspace provider managed it in Part 1 — so
when it runs as a member session inside `packages/workspace/`, it would write
`packages/workspace/mise.toml`, which is wrong.

The fix is to check the session mode in `create_file_mappings()` and return
`None` for files that don't belong at the current level:

```python
from repolish import TemplateMapping, override


class WorkspaceProvider(Provider[WorkspaceContext, WorkspaceInputs]):
    @override
    def create_file_mappings(self, context: WorkspaceContext) -> dict[str, str | TemplateMapping | None]:
        mode = context.repolish.provider.session.mode
        return {
            'mise.toml': 'repolish/mise.toml.jinja' if mode != 'member' else None,
            'dprint.json': 'repolish/dprint.json' if mode != 'member' else None,
            'poe_tasks.toml': 'repolish/poe_tasks.toml.jinja',
        }
```

Returning `None` for a path tells repolish to skip that file entirely for this
session. Members get their own `poe_tasks.toml` (containing only their own
tasks), but `mise.toml` and `dprint.json` only appear at the root.

### Cross-session inputs: members talk to root

Member sessions run first. Each member's `provide_inputs` can emit payloads —
and those payloads are forwarded to the root session's providers. The root
session's `finalize_context` sees inputs from **all** member sessions
combined.

This is the mechanism that makes aggregation possible. A member says "here are
my tasks" by emitting a `WorkspaceInputs` payload. The root's workspace
provider collects them all in `finalize_context` and renders a single
`poe_tasks.toml` that contains every member's contribution.

Within a session, inputs flow in load order (provider A → provider B). Across
sessions, member inputs flow to root. Members cannot see each other's inputs
and cannot see root session inputs — the boundary is one-directional.

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

When root and member behaviour diverge across multiple methods, a
`ModeHandler` subclass keeps each case readable without branching inside every
method:

```python
from repolish import ModeHandler, override


class RootHandler(ModeHandler[WorkspaceContext, WorkspaceInputs]):
    @override
    def create_file_mappings(self, context: WorkspaceContext):
        return {
            'mise.toml': 'repolish/mise.toml.jinja',
            'dprint.json': 'repolish/dprint.json',
            'poe_tasks.toml': 'repolish/poe_tasks.toml.jinja',
        }


class MemberHandler(ModeHandler[WorkspaceContext, WorkspaceInputs]):
    @override
    def create_file_mappings(self, context: WorkspaceContext):
        return {
            'poe_tasks.toml': 'repolish/poe_tasks.toml.jinja',
        }


class WorkspaceProvider(Provider[WorkspaceContext, WorkspaceInputs]):
    root_mode = RootHandler
    member_mode = MemberHandler
```

Repolish dispatches to the right handler automatically based on the workspace
mode. If a mode has no handler set (e.g. `standalone_mode` is not assigned),
the provider falls back to its own methods directly — the same as if no
`ModeHandler` were involved at all.

## What you gain

- **One lock file** — `uv lock` resolves both packages and all their shared
  dependencies together.
- **Atomic changes** — a commit that updates the workspace provider's input
  schema and the python provider's `provide_inputs` in the same PR is safe,
  reviewable, and bisectable.
- **Single CI pipeline** — one workflow runs all provider tests, including the
  integration tests that need both providers installed.
- **Self-managing** — `repolish apply` keeps the devkit repo's own tooling up
  to date from the same templates the providers ship to consumers.

---

Next: [Part 5 — Everything Together](05-using-all-providers.md)
