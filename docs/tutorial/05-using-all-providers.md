# Part 5 — Everything Together

The devkit monorepo is self-managing and fully tested. Now let's walk through
what a consumer project actually looks like when it uses both providers.

## Installing the providers

By Part 5 the two providers live in the `devkit` monorepo on GitHub and are
tagged at `v1.0.0`. Both packages are published from the same repository.
`devkit-python` declares `devkit-workspace` as a Python dependency, so a single
install pulls both:

```bash
uv add git+https://github.com/your-org/devkit@v1.0.0#subdirectory=packages/python
```

If your team also publishes to PyPI:

```bash
uv add devkit-python
```

Then link the providers so repolish knows where their resources live. With both
providers listed in `repolish.yaml`, a single command handles everything:

```bash
repolish link
```

This writes `.repolish/_/provider-info.workspace.json` and
`.repolish/_/provider-info.python.json` — small JSON files that record where
each provider's templates live. Commit these so every developer and CI run uses
exactly the same provider discovery.

## The `repolish.yaml`

```yaml
providers:
  workspace:
    cli: devkit-workspace-link
  python:
    cli: devkit-python-link

post_process:
  - poe format
```

Provider order matters: the workspace provider runs first and declares
`get_inputs_schema() -> type[WorkspaceInputs]`. The python provider runs second
and emits `WorkspaceInputs` payloads. The loader routes those payloads to the
workspace provider's `finalize_context` before any file is written.

`post_process` runs after rendering is complete. Running `poe format` there
means the formatter (dprint + ruff) cleans up the generated output before it is
compared to your project files, so you never see a diff caused purely by
formatting.

## One missing piece

If you followed Part 4 to the letter, linked both providers, and ran
`repolish apply` right now, `my-project` would get a valid `mise.toml` and a
`poe_tasks.toml` — but the file would only contain the format tasks. The
`check-ruff` task would be absent.

The reason: the scaffold generates an empty stub for
`PythonStandaloneHandler.provide_inputs`. The `MemberHandler` was filled in
during Part 4 because the monorepo needed it; the `StandaloneHandler` was never
touched. In standalone mode there is no root session to aggregate for, so the
Python provider must emit its tasks directly the same way the member handler
does — it just targets `WorkspaceProviderInputs` instead of routing through its
own inputs type.

Go back to the devkit monorepo and fill in the stub:

```python
# packages/python/devkit/python/repolish/provider/standalone.py
class PythonStandaloneHandler(ModeHandler[PythonProviderContext, PythonProviderInputs]):
    @override
    def provide_inputs(self, opt):
        tasks = '''\
check-ruff.help = "run ruff linter and formatter check"
check-ruff.cmd = "uvx ruff check ."
'''
        return [WorkspaceProviderInputs(poe_tasks_block=tasks)]
```

Then update the lock file and sync from the devkit root:

```bash
uv lock -U && uv sync
```

Back in `my-project`, repolish picks up the updated provider immediately (it
runs from the installed package, so no reinstall needed after a `uv sync`). Now
`repolish apply` produces the full output.

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

**Pause a file you want to own entirely:**

```yaml
paused_files:
  - dprint.json # we manage our own formatter config
```

**Keep a custom block inside a managed file:**

Templates can expose anchor regions that you control per-project via
`config.anchors`. For example, if `poe_tasks.toml` has an anchor marker for
additional tasks, you can inject project-specific entries without touching the
template:

```yaml
anchors:
  poe-tasks: |
    build-docs.help = "build the mkdocs site"
    build-docs.cmd = "mkdocs build"
```

What anchors are available depends on the provider — check its documentation.

**Override context values:**

Providers can expose named values that projects may override via
`context_overrides`. Whether a value is overridable and what it controls is up
to the provider — check the provider's documentation to see what is available.

## Where to go next

You have now seen everything repolish can do:

- [Concepts](../concepts/overview.md) — if you want to understand the internals
  of what you just used
- [Project Controls](../project-controls/index.md) — the full reference for
  pausing, overriding, and anchoring
- [Provider Development](../provider-development/config-file.md) — every
  `repolish.yaml` field and the Python API

## Checkpoint

Tag `my-project` to mark the completed tutorial state:

```bash
git add -A && git commit -m "chore: apply devkit monorepo providers (part 5)"
git tag part-5
```

You now have a full tag history in `my-project` that tells the story:

| Tag       | What it represents                                      |
| --------- | ------------------------------------------------------- |
| `initial` | Empty project, no repolish                              |
| `part-1`  | Workspace provider applied (`devkit-workspace:v0.1.0`)  |
| `part-2`  | Python provider added (`devkit-python:v0.1.0`)          |
| `part-5`  | Full setup from the `devkit` monorepo (`devkit:v1.0.0`) |

```bash
# See the full journey in one command
git log --oneline initial..part-5
# Or compare any two states
git diff initial part-5
```
