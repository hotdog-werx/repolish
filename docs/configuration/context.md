# Provider Python API

This page covers the Python side of writing a provider: how to define a typed
context model, how to use the `Provider` base class, how to attach per-file
extra context, and how to coordinate with other providers. For how context
sources are merged and how to override values from `repolish.yaml`, see
[Context](../how-it-works/context.md).

## Defining a context model

Every provider should return a typed Pydantic model from `create_context()`. Use
`BaseContext` as the base class - it adds the built-in `repolish` namespace
(repo owner/name, year) without requiring you to import Pydantic directly:

```python
from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    python_version: str = '3.11'
    use_ruff: bool = True


class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()
```

`Provider` is generic in two parameters: the context type and the input schema
(what this provider will accept from other providers via `provide_inputs()`). If
your provider does not receive inputs, use `BaseInputs` as the placeholder.

## Per-file extra context with `TemplateMapping`

`create_file_mappings()` can attach per-file extra context using
`TemplateMapping`. This lets you reuse a single template to generate multiple
files with different typed parameters:

```python
from pydantic import BaseModel
from repolish import BaseContext, BaseInputs, Provider, TemplateMapping


class ModuleCtx(BaseModel):
    module: str


class Ctx(BaseContext):
    pass


class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_mappings(self, context: Ctx):
        return {
            'src/a.py': TemplateMapping('module.py.jinja', ModuleCtx(module='a')),
            'src/b.py': TemplateMapping('module.py.jinja', ModuleCtx(module='b')),
        }
```

During rendering, the template receives the provider's context **merged with**
the `extra_context` fields. Extra context keys shadow provider context keys of
the same name for that file only.

You can inspect what context a specific file received after `repolish apply` by
looking at `.repolish/_/file-ctx/file-context.<slug>.json`. See
[Inspecting context after an apply](../how-it-works/context.md#inspecting-context-after-an-apply).

## Cross-provider coordination

### `provide_inputs()`

A provider can send typed messages to other providers. Declare the output type
in the `provide_inputs()` return and the receiving provider declares the input
type as the second generic parameter of `Provider`:

```python
from pydantic import BaseModel
from repolish import BaseContext, FinalizeContextOptions, Provider, ProviderEntry


class PythonInput(BaseModel):
    python_version: str


class WorkspaceCtx(BaseContext):
    python_version: str = '3.11'


class WorkspaceProvider(Provider[WorkspaceCtx, PythonInput]):
    def create_context(self) -> WorkspaceCtx:
        return WorkspaceCtx()

    # Called after all providers have emitted their initial contexts
    def finalize_context(
        self,
        opt: FinalizeContextOptions[WorkspaceCtx, PythonInput],
    ) -> WorkspaceCtx:
        if opt.received_inputs:
            opt.own_context.python_version = opt.received_inputs[0].python_version
        return opt.own_context
```

### `finalize_context()`

Override `finalize_context()` when you need to derive values after all providers
have emitted their initial context. It runs in a second pass so it can read the
fully assembled context from all peers.

### Reading a peer's context directly

Both `provide_inputs()` and `finalize_context()` receive `opt.all_providers` - a
snapshot of every `ProviderEntry` the loader knows about. The
`get_provider_context()` helper lets you pull a specific provider's context out
of that list by class, without requiring that provider to broadcast anything:

```python
from repolish import BaseContext, BaseInputs, FinalizeContextOptions, Provider, get_provider_context


class MyCtx(BaseContext):
    python_version: str = '3.11'


class MyProvider(Provider[MyCtx, BaseInputs]):
    def finalize_context(
        self,
        opt: FinalizeContextOptions[MyCtx, BaseInputs],
    ) -> MyCtx:
        from other_provider.repolish import OtherProvider

        peer = get_provider_context(OtherProvider, opt.all_providers)
        if peer is not None:
            opt.own_context.python_version = peer.python_version
        return opt.own_context
```

This is the lighter alternative when you only need to read - the peer provider
does not need to implement `provide_inputs()` at all.

**Monorepo note:** `opt.all_providers` only contains providers that are active
in the current run. In a monorepo root run this means root-level providers only;
member providers are processed in separate per-package runs and will not appear
here. If you need data that originates in a member, use the `provide_inputs()`
push pattern from the member toward the root instead.

## Tips

- Keep `create_context()` small and focused - move data-gathering logic into
  private helper functions (see the
  [Quick Start](../getting-started/quick-start.md) for an example of this
  pattern).
- Use `self.templates_root` in `create_file_mappings()` to discover template
  files dynamically (e.g. `self.templates_root.glob('**/*.jinja')`) instead of
  hardcoding paths.
- `finalize_context()` runs before `create_file_mappings()`, so any context
  values derived from received inputs are available when you build your file
  mappings.
- The loader routes `provide_inputs()` payloads by schema match, not by name. A
  payload is delivered to every provider whose `get_inputs_schema()` returns a
  compatible type - if no receiver declares a matching schema the payload is
  silently dropped.
- When implementing a provider that supports multiple workspace modes, check
  `opt.own_context.repolish.workspace.mode` inside `provide_inputs()` to decide
  what (if anything) to broadcast.
