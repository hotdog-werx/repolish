# Provider Facets

A facet holds one managed file's whole contribution set: its context, its
inputs, and its file's mappings, insertions, and validators live together in one
small class. Facets are a way to break a large provider down, not a replacement
for the provider.

## Why facets exist

Adding one file to a provider today means ceremony in four places:

1. A new field on the context model
2. Edits to the mode handlers, where every other file's mappings already live
3. Input handling inside `finalize_context`
4. Template variable wiring

A facet inverts the axis. Instead of three mode classes each holding every file,
one class holds one file and all three modes. Adding a file means adding one
small class instead of touching four files that also describe other files.

## When and where to use facets

Facets are for breaking a provider's per-file work into readable units. Use a
facet when one managed file needs its own context, its own input payload, or its
own validators, and you want that file's logic in one place.

The provider still owns cross-file concerns. These stay on the provider:

- `create_default_copies` and `create_default_symlinks`: plain resources are not
  about one specific managed file
- `create_anchors`: anchors are provider-wide replacements
- Anything that spans files, such as a context field two files share

A provider with two or three simple files does not need facets; the regular
hooks stay the shortest path. Reach for facets when the per-file hooks start
describing files you are not currently working on.

## The contract

A facet subclasses `ProviderFacet` with the same generic style as `Provider`:
the first argument is the facet's context model, the second its input model.

```python
from repolish import (
    BaseContext,
    BaseInputs,
    FacetFinalizeOptions,
    FacetSpec,
    FacetSpecOptions,
    ProviderFacet,
)


class GitignoreInputs(BaseInputs):
    entries: list[str] = []


class GitignoreCtx(BaseContext):
    extra_entries: list[str] = []


class GitignoreFacet(ProviderFacet[GitignoreCtx, GitignoreInputs]):
    name = 'gitignore'

    def finalize_context(self, opt):
        for payload in opt.received_inputs:
            opt.own_context.extra_entries.extend(payload.entries)
        return opt.own_context

    def create_spec(self, opt):
        return FacetSpec(
            file_mappings={'.gitignore': 'gitignore.jinja'},
        )
```

Only `create_spec` is abstract: a facet exists to declare its file. The hooks
mirror the provider's:

| Hook                | Purpose                                                           |
| ------------------- | ----------------------------------------------------------------- |
| `create_context`    | Initial context. Default infers from the generics.                |
| `get_inputs_schema` | Input model for routing. Default infers; `None` for `BaseInputs`. |
| `provide_inputs`    | Emit payloads to other providers. Default: none.                  |
| `finalize_context`  | Apply the routed payloads. Default: pass through.                 |
| `create_spec`       | Declare the file's mappings, insertions, validators.              |

`create_spec` runs after finalize with two contexts: `opt.own_context` is the
facet's finalized context, and `opt.provider_context` is the enclosing
provider's. Siblings are reachable through `provider_context.facets`, so a facet
can read what its siblings decided.

The spec has no `file_copies` field on purpose: plain copies belong to the
provider because they are part of its resource set, not one file's work.

## Registration

Declare facets with the explicit ordered `facets` class attribute, the same
style as `root_mode` and friends:

```python
class WorkspaceProvider(Provider[WorkspaceCtx, WorkspaceInputs]):
    facets = [GitignoreFacet, LicenseFacet]
```

Facet names must be unique within a provider; two facets declaring the same name
is a load error.

## Contexts and modes

After the provider's `create_context` runs, the framework creates each declared
facet's context and stores it in `provider_context.facets[name]`, before
overrides and input exchange, so facet contexts see project overrides and
participate in the input phases.

There are no per-mode facet handlers. A facet runs in every workspace mode and
branches on `ctx.repolish.workspace.mode` itself when content must differ;
`repolish` carries the enclosing provider's alias and session. A mode that does
not feed a facet simply sends no inputs.

## Inputs: the provider routes, facets receive

The provider stays the single routing target. Senders see no new machinery: they
construct the facet's input model exactly as they construct a provider's input
model today, and emit it from `provide_inputs`.

The framework routes each payload by exact schema match. A payload reaches the
provider when it isinstance-matches any schema in the provider's routing list:
the provider's own schema plus its facets' schemas. After the provider's
`finalize_context` runs, each payload that matched a facet's schema is delivered
to that facet's `finalize_context` in `opt.received_inputs`. The framework does
the split; the facet author never filters.

Exact match is deliberate for facet schemas: a structural `model_validate`
fallback against an all-default facet model would deliver one payload to every
facet. The structural fallback stays restricted to the provider's own schema.

## Collection and the collision rule

After the provider's regular hooks are collected, each facet's `create_spec`
merges into the session exactly as if the provider had declared the
contributions through the regular hooks: insertion functions bind to the facet's
own context, and validator and insertion registries follow the same keying
rules.

A destination claimed by both a facet and the provider's regular hooks (file
mappings, insertions, or validators) raises at collection. The same applies to a
destination claimed by two sibling facets. These are load-time authoring
mistakes, the same rule lane-vs-regular collisions follow. Dest claims across
two different providers follow the normal merge rules.

## Templates

The facet's own file renders with `{{ facet.<field> }}` as a shorthand for its
context. Every file the provider renders can also reach any sibling facet
through `{{ facets.<name>.<field> }}`, because the facet map rides on the
provider context.

`{{ facet.* }}` is undefined on files no facet owns; a template that reads it
belongs to a facet-owned file.

## Limits

Facet-aware fast lanes are not supported yet. Lanes are deliberately
context-free (they receive only the `repolish` namespace) while facets live on
the provider context and on routed peer inputs. The `FacetSpec` mirrors the
`FastLaneSpec` shapes so a lane could reference facet mappings later, but
whether that is possible depends on rules that do not exist yet.
