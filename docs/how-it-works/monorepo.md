# Monorepo

Repolish has first-class support for uv workspaces (monorepos). A single
`repolish apply` from the repository root runs a coordinated multi-session
execution — one session for the root and one for each workspace member that has
its own `repolish.yaml`.

## Sessions

A **session** is a bounded group of providers that share information with each
other. Each directory that has a `repolish.yaml` gets its own session:

| Context           | Session role                               |
| ----------------- | ------------------------------------------ |
| Standalone project | one session, `mode = 'standalone'`        |
| Monorepo root     | one session, `mode = 'root'`               |
| Monorepo member   | one session per member, `mode = 'member'` |

Sessions are the unit of isolation and the unit of coordination. Providers
within a session see each other's contexts and inputs freely. Communication
across sessions flows in one direction only: **member sessions emit data upward
to the root session**. A member never receives context or inputs from another
member — each member is fully isolated from its siblings.

```
member A session  ──┐
member B session  ──┼──▶  root session
member C session  ──┘       (aggregates all member data)
```

Cross-session data travels through two typed channels:

| Channel          | Type                  | Description                                                                      |
| ---------------- | --------------------- | -------------------------------------------------------------------------------- |
| `provider_entries` | `list[ProviderEntry]` | The member's full provider list, available to root providers via `all_providers` |
| `emitted_inputs` | `list[BaseInputs]`    | Inputs the member emitted, injected into the root's `finalize_context`           |

## Resolve/apply split

When running in monorepo mode, repolish separates execution into two phases:

**Resolve phase** — every session's provider pipeline runs without writing any
files. Each session produces a snapshot capturing its finalized context, file
mappings, symlinks, and outward cross-session data. Member sessions resolve
first; their outward data is collected and injected into the root session's
resolve step so root providers see the full picture.

**Apply phase** — the resolved sessions are applied in order (root first, then
members). By the time any file is written, every session's full state is already
known.

This design makes cross-session interactions explicit and auditable — the entire
dependency graph between sessions is visible before any filesystem changes happen.

## Provider context fields

The loader injects workspace topology into every provider context under the
`repolish` namespace. Two sub-objects carry monorepo information.

### `repolish.workspace`

Shared by all providers in the session — describes the repository as a whole:

| Field        | Type                                      | Description                                                     |
| ------------ | ----------------------------------------- | --------------------------------------------------------------- |
| `mode`       | `'standalone'` \| `'root'` \| `'member'` | Execution role for this session                                 |
| `root_dir`   | `Path`                                    | Absolute path to the monorepo root                              |
| `package_dir` | `Path` \| `None`                           | Absolute path to the current member; `None` for root/standalone |
| `members`    | `list[MemberInfo]`                        | All discovered workspace members                                |

`mode` defaults to `'standalone'` when no workspace is detected, so existing
providers work unchanged in single-project repos.

### `repolish.provider.session`

Specific to this provider's own role in the current session:

| Field         | Type                                      | Description                                                                  |
| ------------- | ----------------------------------------- | ---------------------------------------------------------------------------- |
| `mode`        | `'standalone'` \| `'root'` \| `'member'` | Same as `workspace.mode`                                                     |
| `member_name` | `str`                                     | Package name of this member (e.g. `pkg-alpha`); `'_root'` for root; `''` for standalone |
| `member_path` | `str`                                     | Repo-relative POSIX path (e.g. `packages/pkg-alpha`); `'.'` for root/standalone |

The two objects differ when a single provider package is installed in multiple
sessions. `repolish.workspace` describes the whole repository;
`repolish.provider.session` describes exactly which part of the repo this
particular provider invocation is targeting.

### `MemberInfo` fields

Each entry in `repolish.workspace.members`:

| Field             | Type              | Description                                           |
| ----------------- | ----------------- | ----------------------------------------------------- |
| `path`            | `Path`            | Repo-relative path to the member directory            |
| `name`            | `str`             | Package name from the member's `pyproject.toml`       |
| `provider_aliases` | `frozenset[str]` | Provider keys declared in the member's `repolish.yaml` |
