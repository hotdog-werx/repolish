# Monorepo Support

Repolish has first-class support for uv workspaces (monorepos). A single
`repolish apply` from the repository root will run a coordinated multi-pass
execution: one pass for the root and one for each workspace member that has
its own `repolish.yaml`.

## Quick start

If you use a **uv workspace**, no extra configuration is needed. Repolish reads
the `[tool.uv.workspace]` table in your root `pyproject.toml` automatically.

```toml
# pyproject.toml (root)
[tool.uv.workspace]
members = ["packages/*"]
```

Each member that has a `repolish.yaml` is treated as a managed package. Members
without a `repolish.yaml` are silently skipped.

Run repolish from the root as usual:

```bash
repolish apply
```

That's it. The root pass runs first, then each member pass runs in discovery
order.

## How it works

Detection and execution happen in three stages:

**1. Detection** — Repolish looks for `[tool.uv.workspace].members` in the root
`pyproject.toml`. If found, it expands the glob patterns and reads each
member's `pyproject.toml` for its package name and `repolish.yaml` for any
declared provider aliases. The result is a `MonorepoContext` object that is
injected into every provider during every pass.

**2. Dry passes** — Before any files are written, Repolish runs each member's
provider pipeline in dry-run mode. This collects the `ProviderEntry` list and
all emitted inputs from every member without touching the filesystem.

**3. Passes in order** — The actual write passes happen in sequence:

- **Root pass** — the root `repolish.yaml` is applied. Member `ProviderEntry`
  objects and emitted inputs are made available to root providers so they can
  read from members (see [Accessing monorepo context](#accessing-monorepo-context-in-providers)).
- **Member passes** — each member's `repolish.yaml` is applied independently.
  Each member only sees its own providers in the write pass.

## Accessing monorepo context in providers

Every provider receives a `repolish` field on its context that contains the
current execution role:

```python
class MyContext(BaseContext):
    repolish: GlobalContext = GlobalContext()
```

The relevant sub-object is `context.repolish.monorepo`:

| Field | Type | Description |
|---|---|---|
| `mode` | `'standalone'` \| `'root'` \| `'package'` | Execution role for this pass |
| `root_dir` | `Path` | Absolute path to the monorepo root |
| `package_dir` | `Path \| None` | Absolute path to the current member (None for root/standalone) |
| `members` | `list[MemberInfo]` | All discovered members |

`mode` defaults to `'standalone'` when no monorepo is detected, so existing
providers work unchanged.

## Writing mode-aware providers

The recommended pattern is a single dispatch on `mode` inside
`create_file_mappings`:

```python
def create_file_mappings(self, context):
    mode = context.repolish.monorepo.mode
    if mode == "root":
        return self._root_mappings(context)
    if mode == "package":
        return self._package_mappings(context)
    return self._standalone_mappings(context)
```

You can apply the same pattern in `provide_inputs` (emit different payloads
from root vs. member) and in `finalize_context` (consume member inputs only
when `mode == "root"`).

### Example: root provider consuming member inputs

```python
class WorkspaceInputs(BaseInputs):
    package_name: str
    has_tests: bool

class WorkspaceProvider(Provider):
    def provide_inputs(self, context, all_providers, idx):
        # Members emit their metadata; root collects it
        if context.repolish.monorepo.mode == "package":
            return [WorkspaceInputs(
                package_name=context.project.name,
                has_tests=(Path("tests").is_dir()),
            )]
        return []

    def finalize_context(self, context, inputs, all_providers, idx):
        if context.repolish.monorepo.mode == "root":
            # inputs contains WorkspaceInputs from every member's dry pass
            context = context.model_copy(update={
                "members": [i.package_name for i in inputs],
            })
        return context
```

During the root pass, `finalize_context` receives all `WorkspaceInputs`
objects collected from every member's dry pass, allowing the root to generate
a workspace-wide summary file (e.g. a top-level `README.md` listing all
packages).

## CLI flags

| Flag | Description |
|---|---|
| `--root-only` | Run only the root pass; skip all member passes |
| `--member <path-or-name>` | Run only the named member (by repo-relative path or package name); skip root pass |
| `--standalone` | Bypass monorepo detection entirely; run a normal single-pass apply in the current directory |

```bash
# Root pass only (fast CI check for root files)
repolish apply --root-only

# Regenerate files for a specific member
repolish apply --member packages/my-lib

# Run directly from inside a member directory (bypasses R10 guard)
cd packages/my-lib
repolish apply --standalone
```

### R10 guard

Running `repolish apply` from inside a workspace member without any flags is
an error. Repolish detects this and exits with code 1:

```
error: packages/my-lib is a member of the monorepo rooted at /repo.
Run `repolish apply` from the root, or use
`repolish apply --member packages/my-lib` from the root.
Pass --standalone to bypass this check and run a single-pass apply here.
```

This prevents accidentally running member-scoped applies when you intended a
full monorepo run.

## Explicit member configuration

By default, Repolish discovers members entirely from `[tool.uv.workspace]`.
If you want to restrict which members are processed by Repolish (e.g. the
workspace is large but only some packages are managed), declare them
explicitly in the root `repolish.yaml`:

```yaml
# repolish.yaml (root)
monorepo:
  members:
    - packages/core
    - packages/utils

providers:
  my-root-provider:
    cli: my-root-provider-link
```

Only the listed paths will receive member passes. Members not listed are
ignored even if they have a `repolish.yaml`.

## Debug output

Each pass writes per-provider context snapshots to `.repolish/_/` inside the
directory where that pass ran. The `monorepo` field in each snapshot confirms
the mode that was active:

```json
{
  "alias": "my-provider",
  "context": {
    "repolish": {
      "monorepo": {
        "mode": "package",
        "root_dir": "/repo",
        "package_dir": "/repo/packages/my-lib",
        "members": [...]
      }
    }
  }
}
```

Use `repolish apply --root-only` followed by inspecting `.repolish/_/` to
verify root-pass context without running member passes.
