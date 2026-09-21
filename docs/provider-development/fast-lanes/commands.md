# Commands

Provider commands are the decoupled sibling of coupled fast lanes.

- Coupled lane: merged into full `repolish apply` and also runnable via the
  provider CLI.
- Provider command: runnable via the provider CLI only; never merged into full
  `repolish apply`.

Use a provider command when the workflow is intentionally developer-invoked
scaffolding rather than repository-wide maintenance.

## How to think about commands

It can help to think of provider commands as the one-off side of the fast-lane
model: provider-owned operations that should be available from the provider CLI
but should not merge into full `repolish apply` runs.

That shape matters conceptually:

- the work is intentional and explicitly invoked by a developer,
- the provider owns the templates and conventions behind it,
- and the operation should stay out of merged repo-wide maintenance runs.

Commands are a good fit because they accept typed inputs. That makes them work
well for scaffolding tasks like generating a React component, bootstrapping a
route module, or creating one targeted config file. They keep the same focused,
provider-owned spirit while using a more expressive contract.

## Declaring a command

Commands are declared with `create_provider_commands()` and backed by an
executor function.

1. Define a typed args model (Pydantic).
2. Define an executor function with signature
   `(args_model_instance, ProviderCommandContext) -> FastLaneSpec`.
3. Return a `ProviderCommandContract` from `create_provider_commands()`.

```python
from pydantic import BaseModel

from repolish import (
  BaseContext,
  BaseInputs,
  FastLaneSpec,
  Provider,
  ProviderCommandContext,
  ProviderCommandContract,
  TemplateMapping,
)


class ReactComponentArgs(BaseModel):
  name: str
  style: str = 'css-module'


def build_component(
  args: ReactComponentArgs,
  ctx: ProviderCommandContext,
) -> FastLaneSpec:
  pascal = ''.join(part.capitalize() for part in args.name.split('-'))
  base = f'src/components/{pascal}'

  # Optional provider-side debug output is allowed.
  print(f'Generating React component: {pascal}')

  return FastLaneSpec(
    file_mappings={
      f'{base}/{pascal}.tsx': TemplateMapping(
        '_repolish.react-component.tsx.jinja',
        extra_context={
          'component_name': pascal,
          'style_mode': args.style,
          'provider_alias': ctx.repolish.provider.alias,
        },
      ),
      f'{base}/{pascal}.test.tsx': TemplateMapping(
        '_repolish.react-component.test.tsx.jinja',
        extra_context={'component_name': pascal},
      ),
      f'{base}/{pascal}.module.css': TemplateMapping(
        '_repolish.react-component.module.css.jinja',
        extra_context={'component_name': pascal},
      ),
    },
  )


class ReactProvider(Provider[BaseContext, BaseInputs]):
  def create_context(self):
    return BaseContext()

  @classmethod
  def create_provider_commands(cls):
    return {
      'component': ProviderCommandContract(
        args_model=ReactComponentArgs,
        executor=build_component,
        summary='Generate a React component module',
      ),
    }
```

With standard CLI wiring (`main = provider_cli(ReactProvider)`), usage looks
like:

```bash
react-provider-cli component --name profile-card --style css-module
```

## One-off work vs coupled lanes

Use a provider command when the operation is fundamentally one-off or
parameterized.

- A command is a good fit when a developer wants to create or bootstrap
  something now.
- A coupled lane is a good fit when the provider should later discover and
  maintain a family of files as part of normal repolish upkeep.

That distinction is why commands and lanes work well together: the command does
the first creation step, and the lane can later maintain the result when the
workflow benefits from recurring enforcement.

## External data and imperative work

Provider commands are also the right place for work that reaches outside the
normal repolish apply loop.

- A command may call another CLI to fetch or transform data before generating
  files.
- A command may make HTTP requests or read from an external service.
- A command may prepare inputs that are only updated when a developer chooses to
  refresh them, not on every PR cadence.

That kind of work should usually stay out of `repolish apply`. Full apply runs
and lane maintenance runs are best when they stay predictable, local, and cheap.
You generally do not want routine repo maintenance to depend on network access,
service availability, or imperative pre-steps that must happen in a particular
order.

It is possible to build a separate wrapper task that downloads data first and
then runs repolish, but that means maintaining another CLI or task surface next
to the provider. Provider commands avoid that split. The provider already has
the templates, already has the fast startup path, and already knows how to turn
typed input plus fetched data into files.

This makes commands a good fit for developer-invoked refresh workflows such as:

- downloading a schema or manifest and rendering derived files from it,
- calling an internal generator CLI and reshaping its output into repo files,
- fetching remote metadata and emitting config or documentation artifacts,
- bootstrapping files whose initial contents depend on live external data.

Those workflows still benefit from repolish's templates and apply pipeline, but
they happen on demand when a developer needs them, not as part of every regular
apply or check run.

## Output behavior

Provider command runs use the same apply engine phases as a lane run. That means
command output remains consistent with other repolish flows.

- The preprocess summary is printed.
- The normal apply/check summary is printed at the end of the run.
- Provider authors may still print their own messages in command code (for
  example progress logs or generated names); those lines appear in command
  output in addition to repolish summaries.

This keeps command UX predictable for users while still allowing provider
authors to add helpful command-specific feedback.
