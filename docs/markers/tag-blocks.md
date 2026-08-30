# Tag Blocks & Anchors

Tag blocks — `repolish-start[name]` … `repolish-end[name]` pairs in a template —
mark a region whose content the **provider** fills with an _anchor value_.
Unlike every other directive family, the developer's project file is never read:
the provider (or `repolish.yaml`) owns what goes between the markers.

These were the first markers in repolish — the escape hatch for templates that
need project-specific statements (extra packages in a Dockerfile, optional
install extras in a Makefile). All marker lines are stripped from the final
file; what remains is the replacement content, ready for Jinja2.

!!! note "Pre-render only"

    Tag blocks are **always resolved in the pre-render
    phase** — anchor content must be in place before Jinja2 sees the template, so
    they carry no `|after-render` suffix. See [Phases](phases.md).

<!-- Align with: tests/integration/test_anchor_overrides.py, tests/directives/test_processors.py -->

## Syntax

A block is a pair of marker lines sharing the same name:

```makefile
## repolish-start[install-extras]
pip install -e ".[dev]"
## repolish-end[install-extras]
```

The comment style is flexible — any prefix before `repolish-start[name]` is
accepted, so use whatever comment syntax fits the file type:

```
# repolish-start[block]            ← Python / TOML / YAML
// repolish-start[block]           ← JavaScript / CSS
<!-- repolish-start[block] -->     ← HTML / Markdown
/* repolish-start[block] */        ← CSS / C
```

The content between the markers is the **default**: it ships in the template and
is used when nothing overrides the anchor.

## Content sources

Repolish resolves each anchor name in this order — later sources win:

1. **Template default** — the content between the markers.
2. **Provider code** — the provider's `create_anchors(context)` method returns a
   dict of names → replacement strings:

   ```python
   def create_anchors(self, context: Ctx) -> dict[str, str]:
       extras = ','.join(['dev', *context.extra_groups])
       return {'install-extras': f'\tpip install -e ".[{extras}]"'}
   ```

3. **Project config** — an `anchors:` mapping in `repolish.yaml`, declared under
   a provider entry:

   ```yaml
   providers:
     mylib:
       cli: mylib-link
       anchors:
         install-extras: 'pip install -e ".[dev,docs]"'
   ```

   Config-level anchors are merged on top of the provider's return value, so you
   only list the keys you want to override. The value is the full replacement
   string — no markers.

   !!! warning "Overrides are global, despite the provider-scoped syntax"
   `anchors:` is _declared_ under a provider entry, but all overrides are merged
   into one global map that every template resolves against. An override under
   `mylib` will also fill a same-named anchor in another provider's templates.
   Namespacing anchor names per provider (see [Naming](#naming)) is currently
   the only isolation.

If no source provides a replacement, the template default is kept — and the
markers are still stripped.

!!! tip "Providers: document your anchors"

    Anchor names only exist in the
    provider's `create_anchors()`, so project maintainers can't discover them. List
    the keys you support and the expected format of each replacement string in your
    provider's docs.

## Worked example

Template (`repolish/Makefile.jinja`):

```makefile
.PHONY: install
install:
## repolish-start[install-extras]
	pip install -e ".[dev]"
## repolish-end[install-extras]
```

With the provider's `create_anchors()` above and `context.extra_groups` set to
`['docs', 'gpu']`, the rendered file is:

```makefile
.PHONY: install
install:
	pip install -e ".[dev,docs,gpu]"
```

## When to use

Anchors are the right tool in a narrow case: the provider must **compute**
content at apply time (assembling values from context) and project developers
override it deliberately via config.

For most "preserve the project's local state" needs, prefer the other families —
they keep the project file as the source of truth and the content visible where
it lives:

- A single value (version, author, URL) → [regex](regex.md)
- A structured section (`[tools]`, dependency lists) →
  [multiregex](multiregex.md)
- A whole developer-owned region → [keep blocks](keep-block.md)

The anchor tradeoff to accept: to customize the injected content you edit
`repolish.yaml` (or the provider computes it), because **editing the file
directly won't stick** — the next apply overwrites the region with whatever the
anchor sources resolve to.

## Naming

Directive names are **global identifiers** across all templates in a run: anchor
values from every provider are merged into one map, and two templates using
`repolish-start[init]` share that one replacement — the provider processed later
silently wins, even in a template owned by another provider.

Until the naming question is settled (see below), **namespace your anchor
names** by prefixing them with the provider or file: `docker-init` instead of
`init`, `mylib-version` instead of `version`.

!!! note "Anchors in v2? An open question"

    Anchors predate typed contexts: they were the escape hatch when templating
    followed cookiecutter's JSON-shaped model, where multiline strings were
    painful. Today's repolish has YAML config and pydantic context models —
    neither has that limitation — and `tests/integration/test_anchor_vs_context.py`
    proves anchors ≡ a Jinja context variable plus a config context override.
    Even the in-template default has an equivalent: a field default on the
    context model.

    **If you want the fix today, use Jinja2 context instead of anchors.** The
    mapping is direct:

    - default → field default on the context model
    - provider-computed → `create_context()`
    - project override → `overrides.context_merge`

    ```python title="repolish.py"
    class Ctx(BaseContext):
        install_extras: str = '\tpip install -e ".[dev]"'
    ```

    ```yaml title="repolish.yaml"
    providers:
      mylib:
        overrides:
          context_merge:
            install_extras: '\tpip install -e ".[minimal]"'
    ```

    Context fields are naturally scoped to their provider too, so the global
    collision problem above never arises.

    If anchors nonetheless survive into v2, per-provider scoping (the provider
    that owns the template wins its own names) is the fix — a breaking change,
    since it requires tracking anchor provenance rather than one merged map.
    The final call is deferred until repolish dogfoods its own providers.
