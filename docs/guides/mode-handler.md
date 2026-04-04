# Mode Handlers

A `ModeHandler` lets you split provider behaviour by workspace role — `root`,
`member`, or `standalone` — without crowding your `Provider` subclass with
`if mode == ...` branches.

## Workspace modes recap

Every repolish session runs in one of three modes:

| Mode         | When it applies                                 |
| ------------ | ----------------------------------------------- |
| `standalone` | A plain, single-project repository              |
| `root`       | The top-level repo in a uv workspace (monorepo) |
| `member`     | A package inside a monorepo                     |

The mode is available in any provider hook via
`context.repolish.workspace.mode`.

## Attaching handlers to a provider

Declare handler classes on the provider using the `root_mode`, `member_mode`,
and `standalone_mode` class attributes. Any attribute that is not set falls back
to the provider's own implementation (or the base-class no-op if neither defines
it).

```python
from repolish import ModeHandler, Provider
from repolish.providers.models.context import BaseContext, BaseInputs, Symlink


class WorkspaceCtx(BaseContext):
    tool_version: str = 'latest'


class RootHandler(ModeHandler[WorkspaceCtx, BaseInputs]):
    def create_file_mappings(self, context):
        # the root gets the aggregating task-runner config
        return {'poe_tasks.toml': '_repolish.poe_tasks.root.toml'}

    def create_default_symlinks(self):
        # only the root should expose this symlink
        return [Symlink(source='configs/root-config.yaml', target='.config/root.yaml')]


class MemberHandler(ModeHandler[WorkspaceCtx, BaseInputs]):
    def create_file_mappings(self, context):
        # members get a simpler per-package config
        return {'poe_tasks.toml': '_repolish.poe_tasks.member.toml'}

    # create_default_symlinks not overridden → no symlinks for members


class WorkspaceProvider(Provider[WorkspaceCtx, BaseInputs]):
    root_mode = RootHandler
    member_mode = MemberHandler
    # standalone_mode not set → falls back to the Provider base no-ops
```

## Resolution order

When repolish calls any hook it uses `call_provider_method` internally:

1. Read `context.repolish.workspace.mode`.
2. Look up the matching handler class (`root_mode`, `member_mode`, or
   `standalone_mode`).
3. If a handler class is registered, instantiate it (once, then cache it) and
   call the hook on it.
4. If no handler is registered — or if the provider overrides the hook directly
   — call the provider's own implementation.

Direct overrides on the `Provider` subclass **always take priority** over mode
handlers. This means you can keep shared logic on the provider and add
mode-specific overrides in handlers.

## Handler attributes

When a handler is first created repolish copies the provider's identity
attributes onto it so handlers can reference them without extra plumbing:

| Attribute        | Value                                                    |
| ---------------- | -------------------------------------------------------- |
| `alias`          | Config key assigned by the loader                        |
| `version`        | Package version (auto-detected)                          |
| `package_name`   | Top-level import name                                    |
| `project_name`   | Distribution name from `pyproject.toml`                  |
| `templates_root` | `provider_root/{mode}/` — mode-scoped template directory |

`templates_root` is the only attribute that is **mode-specific**. For `root`
mode it resolves to `provider_root/root/`, for `member` to
`provider_root/member/`, etc. Use it to glob mode-specific templates:

```python
class RootHandler(ModeHandler[WorkspaceCtx, BaseInputs]):
    def create_file_mappings(self, context):
        # discover every workflow template specific to root
        workflows = list(self.templates_root.glob('.github/workflows/*.yaml'))
        return {f.name: str(f) for f in workflows}
```

## Symlinks per mode

`create_default_symlinks` takes no arguments. Use separate mode handlers to
return different symlinks per workspace role — a `root_mode` handler returns the
symlinks and the `member_mode` handler simply returns `[]`:

```python
class RootHandler(ModeHandler[WorkspaceCtx, BaseInputs]):
    def create_default_symlinks(self):
        return [Symlink(source='configs/shared.yaml', target='.shared.yaml')]


class MemberHandler(ModeHandler[WorkspaceCtx, BaseInputs]):
    def create_default_symlinks(self):
        return []  # no symlinks for members
```

Symlinks are created by both `repolish link` and `repolish apply`, so they are
always in place regardless of which command runs first.

## Supported hooks

Every `Provider` hook is available on `ModeHandler`. Override only the ones that
differ across modes:

| Hook                      | Purpose                              |
| ------------------------- | ------------------------------------ |
| `provide_inputs`          | Emit data to other providers         |
| `finalize_context`        | Merge received inputs into context   |
| `create_file_mappings`    | Return template→destination mappings |
| `create_anchors`          | Return anchor substitutions          |
| `create_default_symlinks` | Return symlinks to create            |
