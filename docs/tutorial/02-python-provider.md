# Part 2 — Python Provider

The workspace provider handles tooling. Now you need Python-specific checks:
ruff for linting and formatting, basedpyright for types. A second provider is
the right place for this — it is a different concern, and not every repo that
uses the workspace provider is a Python project.

## Creating the Python provider

Bootstrap the new package the same way as the workspace provider:

```bash
mkdir devkit-python && cd devkit-python
cat > mise.toml << 'EOF'
[tools]
uv = "latest"
EOF
mise trust && mise install
uvx repolish scaffold . --package devkit.python
```

The scaffold creates the same 11-file structure as before, with the package
namespace `devkit.python` and an entry point `devkit-python-link`.

One extra step: the Python provider sends messages to the workspace provider
using `WorkspaceInputs`, so it needs `devkit-workspace` as a dependency. Add it
to the generated `pyproject.toml`:

```toml
[project]
name = "devkit-python"
version = "0.1.0"
dependencies = ["repolish", "devkit-workspace"] # <-- add devkit-workspace
```

The dependency on `devkit-workspace` is intentional — both providers need to
agree on the same message schema.

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


class WorkspaceContext(BaseContext):
    dprint_version: str = '0.49.0'
    uv_version: str = '0.5.0'
    poe_version: str = '0.29.0'
    extra_poe_tasks: list[str] = []       # populated by finalize_context


class WorkspaceInputs(BaseInputs):
    poe_tasks_block: str = ''
    """A TOML snippet to inject into the poe_tasks.toml template."""
```

Update `WorkspaceProvider` to use `WorkspaceInputs` as its second type
parameter, send its own tasks via `provide_inputs`, and collect everything in
`finalize_context`:

```python
from repolish import FinalizeContextOptions, ProvideInputsOptions, override


class WorkspaceProvider(Provider[WorkspaceContext, WorkspaceInputs]):
    @override
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[WorkspaceContext],
    ) -> list[BaseInputs]:
        tasks = '''\
format.help = "run all formatters"
format.sequence = ["format-dprint"]

format-dprint.help = "run dprint"
format-dprint.cmd = "dprint fmt"
'''
        return [WorkspaceInputs(poe_tasks_block=tasks)]

    @override
    def finalize_context(
        self,
        opt: FinalizeContextOptions[WorkspaceContext, WorkspaceInputs],
    ) -> WorkspaceContext:
        blocks = [inp.poe_tasks_block for inp in opt.received_inputs if inp.poe_tasks_block]
        opt.own_context.extra_poe_tasks = blocks
        return opt.own_context
```

The second type parameter `WorkspaceInputs` is all repolish needs to know which
payloads to route to this provider — no override required. The workspace
provider sends its own format tasks through the same `provide_inputs` path as
every other provider. There is no special case.

Update `poe_tasks.toml.jinja` to render whatever arrived in `extra_poe_tasks`,
including the workspace provider's own contribution:

```toml
[tool.poe.tasks]
{% for block in extra_poe_tasks %}
{{ block }}
{% endfor %}
```

No anchor markers — this is a fully generated file. Jinja handles composition;
the block anchor system is for preserving user edits inside files that already
exist on disk, which is a different problem.

## Sending the message from the Python provider

In `devkit-python`, import `WorkspaceInputs` and emit the ruff tasks:

```python
from devkit.workspace.repolish.models import WorkspaceInputs
from repolish import BaseInputs, Provider, ProvideInputsOptions, override


class PythonContext(BaseContext):
    ruff_version: str = '0.9.0'


class PythonProvider(Provider[PythonContext, BaseInputs]):
    @override
    def create_context(self) -> PythonContext:
        return PythonContext()

    @override
    def provide_inputs(
        self,
        opt: ProvideInputsOptions[PythonContext],
    ) -> list[BaseInputs]:
        tasks = '''\
check-ruff.help = "run ruff linter and formatter check"
check-ruff.cmd = "ruff check . && ruff format --check ."
'''
        return [WorkspaceInputs(poe_tasks_block=tasks)]
```

The loader routes `WorkspaceInputs` payloads to any provider whose second type
parameter is `WorkspaceInputs` — in this case the workspace provider. The Python
provider does not need to know whether a workspace provider is present. If it
is, the tasks appear. If it is not, the payload is silently dropped.

## Apply it

Push `devkit-python` to GitHub so `my-project` can install it the same way it
installed the workspace provider:

```bash
# in devkit-python
git init && git add -A
git commit -m "feat: initial python provider"
git remote add origin https://github.com/your-org/devkit-python
git push origin main
```

In `my-project`, add the second provider alongside the first:

```bash
uv add git+https://github.com/your-org/devkit-python@v0.1.0
```

Because `devkit-python` declares `devkit-workspace` as a dependency, `uv` pulls
both packages. Link the new provider:

```bash
repolish link devkit-python
```

Now `repolish.yaml` lists both:

```yaml
providers:
  workspace:
    cli: devkit-workspace-link
  python:
    cli: devkit-python-link
```

```bash
repolish apply
```

`poe_tasks.toml` now contains both the workspace formatter tasks and the ruff
check tasks, assembled by the workspace provider from inputs it received. Run:

```bash
poe check-ruff
```

Any project that adds `devkit-python` automatically gets the ruff tasks wired
into the workspace task runner — no manual editing, no template duplication.

## Checkpoint

Tag both provider repositories and the consumer project.

In `devkit-python`:

```bash
git add -A && git commit -m "feat: python provider v0.1.0"
git tag v0.1.0
git push origin main --tags
```

In `devkit-workspace` (the input schema changed — bump to `v0.2.0`):

```bash
git add -A && git commit -m "feat: add WorkspaceInputs and finalize_context"
git tag v0.2.0
git push origin main --tags
```

In `my-project`:

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
