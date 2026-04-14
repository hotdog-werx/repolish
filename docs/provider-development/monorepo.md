# Monorepo Setup

Task reference for configuring and running repolish in a uv workspace. See
[Monorepo](../concepts/monorepo.md) for the conceptual overview of
sessions, the resolve/apply split, and cross-session data channels.

## Quick start

If you use a **uv workspace**, no extra configuration is needed. Repolish reads
the `[tool.uv.workspace]` table in your root `pyproject.toml` automatically:

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

The root session runs first; each member session runs in discovery order.

## Auto-staging in root mode

Auto-staging — the automatic copy of every file under `provider/repolish/` to
the project — is **disabled for root sessions**. A provider running with
`mode == 'root'` must return all desired output paths from `create_file_mappings`.
Nothing is written implicitly.

Auto-staging continues to work normally for `'standalone'` and `'member'`
sessions.

## Writing mode-aware providers

Use `context.repolish.workspace.mode` to branch on the current session role:

```python
def create_file_mappings(self, context):
    mode = context.repolish.workspace.mode
    if mode == 'root':
        return self._root_mappings(context)
    if mode == 'member':
        return self._member_mappings(context)
    return self._standalone_mappings(context)
```

For providers whose root, member, and standalone behaviour diverge across
multiple hooks, `ModeHandler` subclasses keep each role readable without inline
branching — see the [Mode Handlers](mode-handler.md) guide.

Member sessions emit inputs upward to the root via `provide_inputs`; the root
collects them in `finalize_context`. See
[Monorepo](../concepts/monorepo.md) for the cross-session channel detail.

## CLI flags

| Flag                       | Description                                                                                      |
| -------------------------- | ------------------------------------------------------------------------------------------------ |
| `--root-only`              | Run only the root session; skip all member sessions                                              |
| `--member <path-or-name>`  | Run only the named member session (by repo-relative path or package name); skip the root session |
| `--standalone`             | Bypass workspace detection entirely; run a single-session apply in the current directory         |

```bash
# Root session only (fast CI check for root files)
repolish apply --root-only

# Regenerate files for a specific member
repolish apply --member packages/my-lib

# Run directly from inside a member directory
cd packages/my-lib
repolish apply --standalone
```

### Running from inside a member directory

Running `repolish apply` from inside a workspace member without `--standalone`
is an error. Repolish detects that the current directory is a managed member and
exits with a helpful message:

```
error: packages/my-lib is a member of the monorepo rooted at /repo.
Run `repolish apply` from the root, or use
`repolish apply --member packages/my-lib` from the root.
Pass --standalone to bypass this check and run a standalone session here.
```

This prevents accidentally running a member-scoped apply when you intended a
full-workspace run.

## Explicit member configuration

By default, repolish discovers members entirely from `[tool.uv.workspace]`. To
restrict which members receive sessions — useful when only some packages in a
large workspace are managed — declare them in the root `repolish.yaml`:

```yaml
# repolish.yaml (root)
workspace:
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
directory where that session ran. The `workspace` field in each snapshot confirms
the mode that was active:

```json
{
  "alias": "my-provider",
  "context": {
    "repolish": {
      "workspace": {
        "mode": "member",
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

