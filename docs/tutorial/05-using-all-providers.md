# Part 5 — Everything Together

The devkit monorepo is self-managing and fully tested. Now let's walk through
what a consumer project actually looks like when it uses both providers.

## Installing the providers

The consumer project installs both providers from PyPI (or from git during
development):

```bash
uv add --dev devkit-workspace devkit-python
```

Link them so repolish knows where their resources live:

```bash
repolish link devkit-workspace
repolish link devkit-python
```

This writes `.repolish/_/provider-info.workspace.json` and
`.repolish/_/provider-info.python.json` — small JSON files that record where
each provider's templates live. You commit these files so every developer and
CI run uses exactly the same provider discovery.

## The `repolish.yaml`

```yaml
providers:
  workspace:
    cli: devkit-workspace-link
    context_overrides:
      dprint_version: '0.51.0'    # pin a newer dprint for this project

  python:
    cli: devkit-python-link
    context_overrides:
      ruff_version: '0.9.3'       # pin a specific ruff

post_process:
  - poe format
```

Provider order matters: the workspace provider runs first and declares
`get_inputs_schema() -> type[WorkspaceInputs]`. The python provider runs
second and emits `WorkspaceInputs` payloads. The loader routes those payloads
to the workspace provider's `finalize_context` before any file is written.

`post_process` runs after rendering is complete. Running `poe format` there
means the formatter (dprint + ruff) cleans up the generated output before it
is compared to your project files, so you never see a diff caused purely by
formatting.

## Apply for the first time

```bash
repolish apply
```

What happens under the hood:

1. Both providers are loaded and their contexts merged.
2. The python provider emits `WorkspaceInputs(poe_tasks_block='...')`.
3. The workspace provider's `finalize_context` receives it and populates
   `extra_poe_tasks`.
4. Templates are staged into `.repolish/_/stage/`.
5. Preprocessing: multiregex anchors in `mise.toml` preserve any tool versions
   you have already pinned.
6. Jinja2 renders everything into `.repolish/_/render/`, including the ruff
   tasks that the python provider injected into `poe_tasks.toml`.
7. `poe format` runs against the rendered output.
8. The rendered files are written to your project root.

Your project now has:

```
mise.toml          ← tools pinned, versions from context
poe_tasks.toml     ← workspace tasks + ruff check tasks
dprint.json        ← formatter config
.github/workflows/
  ci.yml           ← from the python provider
```

## Checking for drift

```bash
repolish apply --check
```

This runs the full pipeline but stops before writing. Instead it prints a diff
of what would change. Use this in CI to catch drift early:

```yaml
# .github/workflows/repolish-check.yml
- run: repolish apply --check
```

## Customising without forking

You do not need to fork the providers to make local adjustments.

**Pin a version in one project:**
```yaml
providers:
  workspace:
    cli: devkit-workspace-link
    context_overrides:
      dprint_version: '0.48.0'  # this project lags behind on purpose
```

**Pause a file you want to own entirely:**
```yaml
paused_files:
  - dprint.json    # we manage our own formatter config
```

**Override a single template:**
```yaml
providers:
  python:
    cli: devkit-python-link
    template_overrides:
      .github/workflows/ci.yml: local-templates/ci.yml
```

**Keep a custom block inside a managed file:**

Add anchor markers around the section you own. The provider leaves those
markers in place and those sections are controlled by what `create_anchors`
returns — if you want project-specific injections, use `config.anchors`:

```yaml
anchors:
  # Override the poe-tasks anchor to add a project-specific task
  poe-tasks: |
    format.sequence = ["format-dprint", "check-ruff", "build-docs"]

    format-dprint.cmd = "dprint fmt"
    check-ruff.cmd = "ruff check . && ruff format --check ."
    build-docs.cmd = "mkdocs build"
```

## Where to go next

You have now seen everything repolish can do:

- [How It Works](../how-it-works/overview.md) — if you want to understand the
  internals of what you just used
- [Developer Control](../developer-control/index.md) — the full reference for
  pausing, overriding, and anchoring
- [Configuration](../configuration/config-file.md) — every `repolish.yaml` field
- [Writing a Provider](../guides/writing-a-provider.md) — scaffold a new provider
  with `repolish scaffold`
