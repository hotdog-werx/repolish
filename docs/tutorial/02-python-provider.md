# Part 2 — Python Provider

The workspace provider handles tooling. Now you need Python-specific checks:
ruff for linting and formatting, basedpyright for types. A second provider is
the right place for this — it is a different concern, and not every repo that
uses the workspace provider is a Python project.

## Creating the Python provider

Bootstrap the new package the same way as the workspace provider:

=== "With mise"

    ```bash
    mkdir devkit-python && cd devkit-python
    cat > mise.toml << 'EOF'
    [settings]
    experimental = true
    python.uv_venv_auto = true

    [tools]
    uv = "latest"
    EOF
    mise trust && mise install
    ```

=== "With uv already installed"

    ```bash
    mkdir devkit-python && cd devkit-python
    ```

```bash
uvx repolish scaffold . --package devkit.python
```

> **Note:** substitute the git URL if repolish is not yet on PyPI:
>
> ```bash
> uvx --from "git+https://github.com/hotdog-werx/repolish.git@master" \
>     repolish scaffold . --package devkit.python
> ```

The scaffold creates the same 11-file structure as before, with the package
namespace `devkit.python` and an entry point `devkit-python-link`.

## The task problem

The Python provider needs to add ruff tasks to `poe_tasks.toml`. But
`poe_tasks.toml` is owned by the workspace provider: it is that provider's
template, rendered by that provider. The obvious move — give the Python provider
its own copy of the template — means the two providers now fight over the same
file. Every time you add another provider (docs, security, database...) you
would be doing this again.

What you actually want is a way for the Python provider to **tell** the
workspace provider "here are tasks I need you to add to the file you manage".
The workspace provider stays in control of its own file; the others just
contribute. This is the problem that led to `provide_inputs` and
`finalize_context`.

## Defining the message schema

In `devkit-workspace`, add an inputs model to `models.py`:

```python
from repolish import BaseContext, BaseInputs


class WorkspaceProviderContext(BaseContext):
    dprint_version: str = '0.49.0'
    uv_version: str = '0.5.0'
    poe_version: str = '0.29.0'
    extra_poe_tasks: list[str] = []       # populated by finalize_context


class WorkspaceProviderInputs(BaseInputs):
    poe_tasks_block: str = ''
    """A TOML snippet to inject into the poe_tasks.toml template."""
```

Update `WorkspaceProvider` to use `WorkspaceProviderInputs` as its second type
parameter, send its own tasks via `provide_inputs`, and collect everything in
`finalize_context`:

```python
from typing_extensions import override

from repolish import FinalizeContextOptions, ProvideInputsOptions


class WorkspaceProvider(Provider[WorkspaceProviderContext, WorkspaceProviderInputs]):
    @override
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[WorkspaceProviderContext],
    ) -> list[BaseInputs]:
        tasks = '''\
format.help = "run all formatters"
format.sequence = ["format-dprint"]

format-dprint.help = "run dprint"
format-dprint.cmd = "dprint fmt"
'''
        return [WorkspaceProviderInputs(poe_tasks_block=tasks)]

    @override
    def finalize_context(
        self,
        opt: FinalizeContextOptions[WorkspaceProviderContext, WorkspaceProviderInputs],
    ) -> WorkspaceProviderContext:
        blocks = [inp.poe_tasks_block for inp in opt.received_inputs if inp.poe_tasks_block]
        opt.own_context.extra_poe_tasks = blocks
        return opt.own_context
```

The second type parameter `WorkspaceProviderInputs` is all repolish needs to
know which payloads to route to this provider — no override required. The
workspace provider sends its own format tasks through the same `provide_inputs`
path as every other provider. There is no special case.

Update `poe_tasks.toml.jinja` to render whatever arrived in `extra_poe_tasks`,
including the workspace provider's own contribution:

```toml
[tool.poe.tasks]
{%- for block in extra_poe_tasks %}
{{ block }}
{%- endfor %}
```

No anchor markers — this is a fully generated file. Jinja handles composition;
the block anchor system is for preserving user edits inside files that already
exist on disk, which is a different problem.

Commit and publish these changes to `devkit-workspace` so `devkit-python` can
depend on the updated schema:

```bash
# in devkit-workspace
git add -A && git commit -m "feat: add WorkspaceProviderInputs and finalize_context"
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

## Sending the message from the Python provider

`devkit-python` needs to import `WorkspaceProviderInputs` from
`devkit-workspace`, so add it as a dependency first, pinned to the tag you just
pushed:

```toml
[project]
name = "devkit-python"
version = "0.1.0"
dependencies = [
  "repolish",
  "devkit-workspace @ git+https://github.com/your-org/devkit-workspace@v0.2.0",
]
```

Then run `uv lock -U && uv sync` to install it.

Now import `WorkspaceProviderInputs` and emit the ruff tasks:

```python
from typing_extensions import override

from repolish import BaseInputs, Provider, ProvideInputsOptions

from devkit.python.repolish.models import (
    PythonProviderContext,
    PythonProviderInputs,
)

from devkit.workspace.repolish.models import WorkspaceProviderInputs


class PythonProvider(Provider[PythonProviderContext, PythonProviderInputs]):
    @override
    def create_context(self) -> PythonProviderContext:
        return PythonProviderContext()

    @override
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[PythonProviderContext],
    ) -> list[BaseInputs]:
        tasks = '''\
check-ruff.help = "run ruff linter and formatter check"
check-ruff.cmd = "uvx ruff check ."
'''
        return [WorkspaceProviderInputs(poe_tasks_block=tasks)]
```

The loader routes `WorkspaceProviderInputs` payloads to any provider whose
second type parameter is `WorkspaceProviderInputs` — in this case the workspace
provider. The Python provider does not need to know whether a workspace provider
is present. If it is, the tasks appear. If it is not, the payload is silently
dropped.

## Apply it

Push `devkit-python` to GitHub so `my-project` can install it the same way it
installed the workspace provider:

```bash
# in devkit-python
git init && git add -A
git commit -m "feat: initial python provider"
```

Create an empty repository on GitHub (no README, no `.gitignore`), then connect
and push:

```bash
git remote add origin git@github.com:your-org/devkit-python.git
git branch -M main
git push -u origin main
```

Tag and push the initial release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

In `my-project`, add the second provider alongside the first:

```bash
uv add git+https://github.com/your-org/devkit-python@v0.1.0
```

Because `devkit-python` declares `devkit-workspace@v0.2.0` as a dependency, `uv`
will resolve `devkit-workspace` to `v0.2.0`. If `my-project` still has
`devkit-workspace` listed as a direct dependency pinned to `v0.1.0` you have two
options:

- **Bump it** — update the ref to `@v0.2.0` so the pin matches.
- **Remove it** — drop the direct dependency entirely and let `devkit-python`
  pull the right version transitively.

Either works; removing it is simpler since `devkit-python` already declares the
correct version.

Update `repolish.yaml` to include the new provider:

```yaml
providers:
  workspace:
    cli: devkit-workspace-link
  python:
    cli: devkit-python-link
```

`repolish apply` will link any unlinked provider automatically, so the explicit
link step is optional. Run apply directly:

```bash
repolish apply
```

`poe_tasks.toml` now contains both the workspace formatter tasks and the ruff
check tasks, assembled by the workspace provider from inputs it received.

`my-project` does not have any Python files yet, so ruff has nothing to check.
Add one:

```python
# python_script.py
def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
```

Then run:

```bash
poe check-ruff
```

Any project that adds `devkit-python` automatically gets the ruff tasks wired
into the workspace task runner — no manual editing, no template duplication.

## Checkpoint

Both provider repositories were already tagged and pushed during this part:

- `devkit-workspace` — `v0.2.0` (schema update)
- `devkit-python` — `v0.1.0` (initial release)

Tag `my-project` to mark the end of Part 2:

```bash
git add -A && git commit -m "chore: apply python provider"
git tag part-2
```

Compare `part-1` to `part-2` in `my-project` to see the ruff tasks appear in
`poe_tasks.toml`:

```bash
git diff part-1 part-2
```

---

Next: [Part 3 — The Sync Problem](03-keeping-in-sync.md)
