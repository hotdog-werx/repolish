# Tutorial

This tutorial follows the real path that led to repolish becoming what it is
today. Rather than presenting the full feature set up front, each part
introduces a new problem and shows exactly why the next feature was needed.

By the end you will have touched every major concept in repolish and have a
mental model of how the pieces connect.

## What you will build

| Part | What you build | Concepts introduced |
|------|---------------|---------------------|
| [1 — Workspace Provider](01-workspace-provider.md) | A provider that manages `mise.toml` and a `poe_tasks.toml` with dprint formatter tasks | Provider structure, templates, anchors |
| [2 — Python Provider](02-python-provider.md) | A second provider that adds ruff checks and contributes its tasks to the workspace provider | Provider inputs, `provide_inputs`, `finalize_context` |
| [3 — The Sync Problem](03-keeping-in-sync.md) | Two separate provider repos applied across multiple projects | The pain of keeping separate repos in sync |
| [4 — Going Monorepo](04-monorepo.md) | Combining both providers into one monorepo | Monorepo mode, testing providers together |
| [5 — Everything Together](05-using-all-providers.md) | A consumer project that uses both providers at once | Full `repolish.yaml` configuration, sessions |

## Prerequisites

- repolish installed (`pip install repolish`)
- `mise` installed (for tool management)
- `uv` installed (for Python packaging)
- Basic familiarity with Python packaging (`pyproject.toml`)

You do not need to know how repolish works internally — that is what this
tutorial is for.
