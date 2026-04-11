# Tutorial

This tutorial follows the real path that led to repolish becoming what it is
today. Rather than presenting the full feature set up front, each part
introduces a new problem and shows exactly why the next feature was needed.

By the end you will have touched every major concept in repolish and have a
mental model of how the pieces connect.

## What you will build

| Part                                                 | What you build                                                                              | Concepts introduced                                   |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| [1 — Workspace Provider](01-workspace-provider.md)   | A provider that manages `mise.toml` and a `poe_tasks.toml` with dprint formatter tasks      | Provider structure, templates, anchors                |
| [2 — Python Provider](02-python-provider.md)         | A second provider that adds ruff checks and contributes its tasks to the workspace provider | Provider inputs, `provide_inputs`, `finalize_context` |
| [3 — The Sync Problem](03-keeping-in-sync.md)        | Two separate provider repos applied across multiple projects                                | The pain of keeping separate repos in sync            |
| [4 — Going Monorepo](04-monorepo.md)                 | Combining both providers into one monorepo                                                  | Monorepo mode, testing providers together             |
| [5 — Everything Together](05-using-all-providers.md) | A consumer project that uses both providers at once                                         | Full `repolish.yaml` configuration, sessions          |

## Companion repositories

The tutorial is written around three real repositories you will create as you
follow along.

| Repository         | Role                                                                     | Created in    |
| ------------------ | ------------------------------------------------------------------------ | ------------- |
| `my-project`       | The consumer project you apply providers to throughout the tutorial      | Before Part 1 |
| `devkit-workspace` | The first provider (workspace tooling)                                   | Part 1        |
| `devkit-python`    | The second provider (Python checks), lives separately at first           | Part 2        |
| `devkit`           | The providers monorepo — `devkit-workspace` and `devkit-python` combined | Part 4        |

Each part ends with a **checkpoint** block that tells you which repositories to
tag and what tag to use. By the end of the tutorial every meaningful state has a
permanent reference you can link to from notes, PRs, or documentation.

## Prerequisites

- [`mise`](https://mise.jdx.dev) installed

`mise` will install everything else — `uv`, `dprint`, `poethepoet` — as the
tutorial progresses. `repolish` itself gets installed via `uv` once `mise` has
it available.

You do not need to know how repolish works internally — that is what this
tutorial is for.
