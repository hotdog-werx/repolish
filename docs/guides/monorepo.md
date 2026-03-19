# Monorepo Support

Repolish has first-class support for uv workspaces (monorepos). A single
`repolish apply` from the repository root will run a coordinated multi-session
execution: one session for the root and one for each workspace member that has
its own `repolish.yaml`.

## Sessions

A **session** is a bounded group of providers that share information with each
other. Each directory context in a repository is its own session:

| Context            | Session role                               |
| ------------------ | ------------------------------------------ |
| Standalone project | one session, `mode = 'standalone'`         |
| Monorepo root      | one session, `mode = 'root'`               |
| Monorepo member    | one session per member, `mode = 'package'` |

Sessions are the unit of isolation and the unit of coordination. Providers
within a session see each other's contexts and inputs freely. Communication
across sessions flows in one direction only: **member sessions emit data upward
to the root session**. A member session never receives context or inputs from
another member session — each member is fully isolated from its siblings.

```
member A session  ──┐
member B session  ──┼──▶  root session
member C session  ──┘       (aggregates all member data)
```

This one-way channel keeps members independent and composable. The root is the
only place that sees the full picture across all members, making it the natural
location for workspace-wide generated files such as a top-level task runner
configuration (e.g. a `Makefile` or `poe_tasks.toml` that aggregates commands
from every member).

Cross-session data travels through two typed channels:

| Channel            | Type                  | Description                                                                           |
| ------------------ | --------------------- | ------------------------------------------------------------------------------------- |
| `provider_entries` | `list[ProviderEntry]` | The member's full provider list, available to root providers via `all_providers`      |
| `emitted_inputs`   | `list[BaseInputs]`    | Inputs the member emitted before routing, injected into the root's `finalize_context` |

### The resolve/apply split

When running in monorepo mode, Repolish separates execution into two phases:

**Resolve phase** — every session's provider pipeline is executed without
writing any files. Each session produces a `ResolvedSession` snapshot that
captures the finalized provider contexts, file mappings, symlinks, and the
outward cross-session data (`provider_entries` + `emitted_inputs`). Member
sessions are resolved first; their outward data is collected and injected into
the root session's resolve step so root providers see the full picture.

**Apply phase** — the resolved sessions are applied in order (root first, then
members). By the time any file is written, every session's full state is already
known.

This design makes cross-session interactions explicit and auditable: the entire
dependency graph between sessions is visible before any filesystem changes
happen.

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

That's it. The root session runs first, then each member session runs in
discovery order.

## How it works

Detection and execution happen in three stages:

**1. Detection** — Repolish looks for `[tool.uv.workspace].members` in the root
`pyproject.toml`. If found, it expands the glob patterns and reads each member's
`pyproject.toml` for its package name and `repolish.yaml` for any declared
provider aliases. The result is a `WorkspaceContext` object that is injected
into every provider during every session.

**2. Resolve phase** — Before any files are written, Repolish resolves each
session's provider pipeline. This includes an internal dry pass (the resolve
phase) that captures the `ProviderEntry` list and all emitted inputs from every
member without touching the filesystem. Member session data is then injected
into the root session's resolve step.

**3. Apply phase** — The resolved sessions are applied in sequence:

- **Root session** — the root `repolish.yaml` is applied. Member `ProviderEntry`
  objects and emitted inputs are available to root providers so they can read
  from members (see
  [Accessing monorepo context](#accessing-monorepo-context-in-providers)).
  **Auto-staging is disabled during the root session** — only files explicitly
  returned by `create_file_mappings` are written to the root directory. This
  prevents providers designed for member repos from accidentally littering the
  monorepo root with member-scoped files.
- **Member sessions** — each member's `repolish.yaml` is applied independently.
  Each member only sees its own providers. Auto-staging works normally here.

## Accessing monorepo context in providers

Every provider receives a `repolish` field on its context that contains the
current execution role:

```python
class MyContext(BaseContext):
    repolish: GlobalContext = GlobalContext()
```

The relevant sub-object is `context.repolish.monorepo`:

| Field         | Type                                      | Description                                                    |
| ------------- | ----------------------------------------- | -------------------------------------------------------------- |
| `mode`        | `'standalone'` \| `'root'` \| `'package'` | Execution role for this session                                |
| `root_dir`    | `Path`                                    | Absolute path to the monorepo root                             |
| `package_dir` | `Path \| None`                            | Absolute path to the current member (None for root/standalone) |
| `members`     | `list[MemberInfo]`                        | All discovered members                                         |

`mode` defaults to `'standalone'` when no monorepo is detected, so existing
providers work unchanged.

## Writing mode-aware providers

!!! note "Root sessions require explicit file mappings" Auto-staging (the
automatic copy of every file under `provider/repolish/` to the project) is
**disabled** for root sessions. A provider running with `mode == "root"` must
return all desired output paths from `create_file_mappings` — nothing is written
implicitly. Auto-staging continues to work normally for `'standalone'` and
`'package'` sessions.

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

You can apply the same pattern in `provide_inputs` (emit different payloads from
root vs. member) and in `finalize_context` (consume member inputs only when
`mode == "root"`). Member providers should never attempt to read inputs from
other members — that data simply isn't present in a member session.

### Example: root provider aggregating member metadata

A common use-case is generating a workspace-wide task runner file at the root —
for example a `poe_tasks.toml` or `Makefile` that delegates to each member. The
root provider collects member metadata emitted during the resolve phase and uses
it to render the aggregated file.

```python
class MemberInfo(BaseInputs):
    package_name: str
    has_tests: bool
    has_lint: bool

class WorkspaceProvider(Provider):
    def provide_inputs(self, context, all_providers, idx):
        # Each member session emits its own metadata upward.
        # Member sessions never see each other's inputs.
        if context.repolish.monorepo.mode == "package":
            return [MemberInfo(
                package_name=context.project.name,
                has_tests=Path("tests").is_dir(),
                has_lint=Path("pyproject.toml").is_file(),
            )]
        return []

    def finalize_context(self, context, inputs, all_providers, idx):
        if context.repolish.monorepo.mode == "root":
            # inputs contains MemberInfo from every member — root is the only
            # session that receives cross-session data.
            context = context.model_copy(update={
                "members": inputs,  # all MemberInfo objects, one per member
            })
        return context
```

During the root session, `finalize_context` receives all `MemberInfo` objects
collected from every member session's resolve phase. The root provider can then
render a workspace-level `poe_tasks.toml` that wires up `test`, `lint`, and
other tasks for every member automatically — something no single member session
could do on its own since members are isolated from each other.

## CLI flags

| Flag                      | Description                                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------------ |
| `--root-only`             | Run only the root session; skip all member sessions                                              |
| `--member <path-or-name>` | Run only the named member session (by repo-relative path or package name); skip the root session |
| `--standalone`            | Bypass monorepo detection entirely; run a single-session apply in the current directory          |

```bash
# Root session only (fast CI check for root files)
repolish apply --root-only

# Regenerate files for a specific member
repolish apply --member packages/my-lib

# Run directly from inside a member directory (bypasses R10 guard)
cd packages/my-lib
repolish apply --standalone
```

### R10 guard

Running `repolish apply` from inside a workspace member without any flags is an
error. Repolish detects this and exits with code 1:

```
error: packages/my-lib is a member of the monorepo rooted at /repo.
Run `repolish apply` from the root, or use
`repolish apply --member packages/my-lib` from the root.
Pass --standalone to bypass this check and run a standalone session here.
```

This prevents accidentally running member-scoped applies when you intended a
full monorepo run.

## Explicit member configuration

By default, Repolish discovers members entirely from `[tool.uv.workspace]`. If
you want to restrict which members are processed by Repolish (e.g. the workspace
is large but only some packages are managed), declare them explicitly in the
root `repolish.yaml`:

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

Only the listed paths will receive member sessions. Members not listed are
ignored even if they have a `repolish.yaml`.

## Debug output

Each session writes per-provider context snapshots to `.repolish/_/` inside the
directory where that session ran. The `monorepo` field in each snapshot confirms
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

Use `repolish apply --root-only` followed by inspecting `.repolish/_/` to verify
root session context without running member sessions.
