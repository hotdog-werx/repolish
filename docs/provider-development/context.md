# Provider Python API

This page covers the Python side of writing a provider: how to define a typed
context model, how to use the `Provider` base class, how to attach per-file
extra context, and how to coordinate with other providers. For how context
sources are merged and how to override values from `repolish.yaml`, see
[Context](../concepts/context.md).

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
[Inspecting context after an apply](../concepts/context.md#inspecting-context-after-an-apply).

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

## Promoting files to the repo root

In a monorepo, a member provider can push files to the monorepo **root**
directory using `promote_file_mappings()`. This is useful for files that belong
to the whole workspace — shared CI workflows, a root-level `CODEOWNERS`, a
common `Makefile` target — but whose content is derived from member-level
context.

```python
from repolish import BaseContext, BaseInputs, ModeHandler, Provider, TemplateMapping


class Ctx(BaseContext):
    python_version: str = '3.11'


class MemberHandler(ModeHandler[Ctx, BaseInputs]):
    def create_file_mappings(self, context: Ctx):
        # files inside the member package
        return {'pyproject.toml': 'pyproject.toml.jinja'}

    def promote_file_mappings(self, context: Ctx):
        # these paths land at the monorepo root, not the member directory
        return {
            '.github/workflows/ci.yaml': TemplateMapping(
                source_template='ci.yaml.jinja',
                promote_conflict='identical',
            ),
        }


class MyProvider(Provider[Ctx, BaseInputs]):
    member_mode = MemberHandler
```

Destination paths in `promote_file_mappings()` are resolved relative to the
**monorepo root**, not the member directory. Repolish collects all promotions
after every member session has run and writes them during the root pass.

### Conflict resolution

When two members promote the same destination path,
`TemplateMapping.promote_conflict` controls what happens:

| Strategy      | Behaviour                                                                      |
| ------------- | ------------------------------------------------------------------------------ |
| `"identical"` | Both outputs must be byte-for-byte equal; fail loudly if they differ (default) |
| `"last_wins"` | The last member session processed silently wins                                |
| `"error"`     | Fail immediately on any conflict, regardless of content                        |

The `"identical"` default is deliberately strict: if two members both produce
the same CI workflow from the same template the rendered bytes must match — a
divergence is a bug worth surfacing.

### Restrictions

- `promote_file_mappings()` is only meaningful in **member** mode. Repolish
  emits a warning and ignores the return value when called in `root` or
  `standalone` mode — use `create_file_mappings()` for files that should land in
  the root or standalone project directory.
- If the rendered source file is missing from the member's render output,
  repolish logs a warning and skips that entry.
- Use a `ModeHandler` (see [Mode Handlers](mode-handler.md)) to keep the
  member-only logic cleanly separated from root and standalone behaviour.

## Anchors

`create_anchors()` returns a mapping of named text blocks that other templates
can reference with the `repolish-start` / `repolish-end` comment pair. This
allows a provider to inject or update a specific region of a file without owning
the whole file:

```python
class MyProvider(Provider[Ctx, BaseInputs]):
    def create_anchors(self, context: Ctx) -> dict[str, str]:
        return {
            'build-matrix': f'python-version: ["{context.python_version}"]',
        }
```

Any template — from any provider — can then declare the target region:

```yaml
# .github/workflows/ci.yaml
jobs:
  test:
    strategy:
      matrix:
        ## repolish-start[build-matrix]
        python-version: ['3.11']
        ## repolish-end[build-matrix]
```

After `repolish apply` the bracketed region is replaced with the anchor value.
Anchors from multiple providers are merged; if two providers declare the same
anchor key the later provider in load order wins.

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
- **Project-configurable context:** a provider can expose an `*_args` or
  `*_config` field in its context model as a hook for projects to influence how
  context is derived. The project sets the field via `context_overrides:` and
  the provider reads it in `finalize_context()` (which runs after all overrides
  are applied) to generate the rest of its context:

  ```python
  from pydantic import BaseModel
  from repolish import BaseContext, BaseInputs, FinalizeContextOptions, Provider


  class MyProviderArgs(BaseModel):
      api_version: str = 'v1'


  class MyProviderCtx(BaseContext):
      my_provider_args: MyProviderArgs = MyProviderArgs()
      api_url: str = 'https://api.example.com/v1'


  class MyProvider(Provider[MyProviderCtx, BaseInputs]):
      def create_context(self) -> MyProviderCtx:
          return MyProviderCtx()

      def finalize_context(
          self,
          opt: FinalizeContextOptions[MyProviderCtx, BaseInputs],
      ) -> MyProviderCtx:
          ver = opt.own_context.my_provider_args.api_version
          opt.own_context.api_url = f'https://api.example.com/{ver}'
          return opt.own_context
  ```

  ```yaml
  # repolish.yaml — project-side override
  context_overrides:
    my_provider_args:
      api_version: v2
  ```

  This is a convention, not a framework feature. The provider decides which
  fields to treat as inputs and how to act on them.
