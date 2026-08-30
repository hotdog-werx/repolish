# Phases

Phases apply **only to templates** — provider-owned `.jinja` files — so this
page is for provider developers. Directives never run on project-owned files:
those are filled by [Insertions](insertions.md), which have no phase concept
(they run in a single pass after rendering, once files exist on disk).

Directives are processed in two phases:

1. **`pre-render`** (default) — runs on staged templates, before Jinja2.
2. **`after-render`** (opt-in) — runs on rendered files, after Jinja2.

All processed directive lines are stripped from the final output, so project
files stay clean either way.

<!-- Align with: tests/directives/test_file_api.py, tests/integration/test_directives_after_render.py -->

## Why two phases?

A directive written literally in a template can always be found before
rendering. But a directive that lives **inside Jinja-generated content** — a
loop body, a conditional block — doesn't exist until Jinja2 has produced the
final file content. Such a directive must declare the `after-render` phase so
repolish evaluates it on the rendered output instead.

```jinja
## repolish-keep-block[user-note|after-render]: start="<!-- note-start -->" end="<!-- note-end -->"
<!-- note-start -->
{% for item in items %}
- {{ item }}
default note for {{ item }}
<!-- note-end -->
{% endfor %}
```

Each rendered repetition carries its own keep block, and each one is reconciled
against the developer's current file after rendering.

## The `|after-render` suffix

Append `|after-render` to the directive name **inside the square brackets**:

```
repolish-keep-block[notes|after-render]: start="..." end="..."
   directive kind     name   phase
```

With no suffix the directive runs in `pre-render` — that is the default for
every directive family.

The suffix works on all directive families except tag blocks:

- `repolish-regex[...]`
- `repolish-multiregex-block[...]` / `repolish-multiregex[...]`
- `repolish-keep-block[...]` / `repolish-keep-rest[...]` /
  `repolish-keep-header[...]`

Tag blocks (`repolish-start[...]` / `repolish-end[...]`) are anchors-driven and
are **always replaced before Jinja2 runs** — content injected after rendering
would never be seen by the template engine.

<!-- insertion-candidate: the support table above mirrors which registry families accept a phase suffix — could be generated from the registry once directives self-document -->

### Invalid suffixes

An unrecognized suffix (`[notes|after_rendr]`, `[notes|post-render]`) logs a
warning and falls back to `pre-render` — the directive is never silently
dropped.

## Worked example

After-render pays off when the _values_ in the rendered file are assembled from
merged context. Say a mise provider asks the other providers which tools they
need, then renders them with default versions — while the developer has pinned
real versions in their current `mise.toml`.

One way to preserve those versions is to read the developer's file in Python,
during context creation, and seed the versions before rendering:

```python
# provider code — reconciliation hidden in context assembly
current_versions = parse_mise_toml(project_root / 'mise.toml')
tools = {name: current_versions.get(name, default) for ...}
```

That works, but the reconciliation is invisible in the template and every
provider rediscovers it. The declarative alternative: keep the provider code
deciding **which tools ship** (context — legitimately provider logic), and let
an `|after-render` multiregex directive preserve the **versions** — Jinja
renders the provider's tool list with defaults, then the directive pulls each
version from the developer's existing file:

```toml
# repolish/mise.toml.jinja
[tools]
## repolish-multiregex-block[tools|after-render]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools|after-render]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
{% for tool, default in tools.items() %}
{{ tool }} = "{{ default }}"
{% endfor %}
```

No provider code reads project files; the template itself declares what
survives. For a single value (a version line, an author field) the same idea
uses `repolish-regex[name|after-render]` instead of the block pair.

<!-- Align with: tests/integration/test_directives_after_render.py::test_after_render_multiregex_preserves_only_selected_provider_sections -->

## The full pipeline

An _apply_ is one run of the `repolish apply` command over your project (see
[repolish apply](../reference/apply.md)). During an apply, each provider-managed
file goes through this pipeline in order:

1. **Pre-render phase** on staged templates:
   1. Tag blocks — replaced with provider-supplied anchor content
      (`create_anchors()` / `anchors:` in `repolish.yaml`).
   2. Keep directives — regions restored from the developer's file.
   3. Regex directives — lines adopted from the developer's file.
   4. Multiregex directives — structured blocks merged.
2. **Jinja2 rendering.**
3. **After-render phase** on rendered files — only directives carrying the
   `|after-render` suffix; same family order as step 1.
4. **Insertions** are written to the files on disk.
5. **Post-process formatting** (provider mode hooks, e.g. formatters).

<!-- insertion-candidate: step order mirrors FAMILIES ordering in repolish/directives/registry.py and the after-render call sites in commands/apply — could be generated from the pipeline code -->

Note what this means in practice: values captured in the `pre-render` phase are
substituted into the template **before** Jinja2 sees it, so a
`repolish-regex`-adopted line is what Jinja renders around — while an
`|after-render` directive operates on content that is already final.

!!! note "Phases for project-owned files?" Insertions already touch project
files in what is effectively the after-render moment — once generated files
exist on disk — so a literal `|after-render` suffix there would add nothing.
What _is_ coming is the other half of that picture: **insertion zones** (the
planned `repolish-insert` directive, see the
[quadrant diagram](index.md#the-four-quadrants)), where a provider declares a
fillable zone in a _template_. Its zones survive rendering into the generated
file, and the insertion phase fills them — so the after-render phase is where
those declarations will be parsed.
