# Preprocessors

Repolish processes directives in two phases, `pre-render` (default) and
`after-render` (opt-in via a `|after-render` suffix) — see
[Phases](../markers/phases.md). All processed directive lines are stripped from
final output so project files stay clean.

The most common directives are **regex** and **multiregex**: they live inside
the template file itself and read values directly from your current project
file. This makes templates self-contained - no separate config or provider code
is needed to preserve local state. Block anchors and keep directives are simpler
alternatives for cases where the provider (not the project file) decides what a
section contains or which zone should be preserved.

## Regex directives

Regex directives — adopting single values from your current project file via
`## repolish-regex[name]: pattern` — are covered in
[Regex](../markers/regex.md), including the two-sided contract (the pattern
must match the template default too) and the indentation trim safeguard.

## Multiregex directives

For structured blocks (a `[tools]` section in a TOML file, a `requirements`
list, etc.) multiregex directives let you merge additions from the provider
while keeping versions you have already pinned locally.

```toml
[tools]
## repolish-multiregex-block[tools|after-render]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools|after-render]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
uv = "0.0.0"
dprint = "0.0.0"
```

The block pattern locates the relevant section; the line pattern extracts
key-value pairs. Your existing versions are preserved for matching keys; new
provider keys are appended.

## Block anchors

Tag blocks — `repolish-start[name]` … `repolish-end[name]` pairs filled by
provider-supplied anchor content — are covered in
[Tag Blocks & Anchors](../markers/tag-blocks.md).

## Keep directives

Keep directives preserve developer-owned content inside provider-managed files
without forcing you to handwrite multiline regex patterns. Use them when you
want to keep a visible region in place if the project file already has one,
while still shipping a sensible template default for fresh projects.

### Keep a bounded region

Use `repolish-keep-block` when the developer-owned content sits between two
explicit markers.

```markdown
## repolish-keep-block[readme-custom-block|after-render]: start="<!-- start -->" end="<!-- end -->"

<!-- start -->

Default block content

<!-- end -->
```

If the current project file already has a matching marker pair, repolish keeps
that content. Otherwise the template default remains.

You can also use a dynamic closing boundary with `end-regex` when a literal end
marker is awkward or unavailable (for example, stop at the next loop item):

```yaml
## repolish-keep-block[provider-additional|after-render]: start="# additional-paths" end-regex="^provider[0-9]+:$"
{% for idx in providers %}
provider{{ idx }}:
   - static{{ idx }}
   # additional-paths
   - default{{ idx }}
{% endfor %}
```

With `end-regex`, repolish searches forward from each `start` marker for the
first matching line. If no match is found before the directive segment ends, the
region closes at the segment end.

When several sibling `keep-block` directives use the same `start`/`end` markers
in one file, repolish matches them in encounter order and restores local blocks
in that same order.

One directive is enough — no need to give each block a different name:

```markdown
## repolish-keep-block[notes]: start="<!-- notes-start -->" end="<!-- notes-end -->"

## Installation

<!-- notes-start -->

_No notes yet._

<!-- notes-end -->

## Usage

<!-- notes-start -->

_No notes yet._

<!-- notes-end -->
```

If the project file already has both marker pairs with developer content:

```markdown
## Installation

<!-- notes-start -->

Run `pip install mylib` with Python 3.11+.

<!-- notes-end -->

## Usage

<!-- notes-start -->

Import and call `mylib.run()` after configuring credentials.

<!-- notes-end -->
```

The output preserves both blocks in place — first block matched to first, second
to second, and so on:

```markdown
## Installation

<!-- notes-start -->

Run `pip install mylib` with Python 3.11+.

<!-- notes-end -->

## Usage

<!-- notes-start -->

Import and call `mylib.run()` after configuring credentials.

<!-- notes-end -->
```

### Keep everything from a marker to EOF

Use `repolish-keep-rest` when a marker introduces a developer-owned tail.

```gitignore
## repolish-keep-rest[repo-overrides]: marker="## repo-overrides"
## repo-overrides
# Placeholder
```

Everything from the marker line to EOF is preserved from the project file when
present.

### Keep the header up to a marker

Use `repolish-keep-header` when the developer owns the top of the file and the
provider owns the section below the marker.

`repolish-keep-header` must appear at the start of the template file. If placed
later in the file, repolish ignores the directive to avoid duplicating content
that may already have been emitted before the directive line.

```toml
## repolish-keep-header[repo-header]: marker="## managed-start"
Intro text the developer can edit
## managed-start
Provider-managed content below
```

The header is preserved from the project file, while the provider-managed tail
continues to come from the template.

## Processing order

The full pipeline — pre-render phase, Jinja2 rendering, after-render phase,
insertions, and post-process formatting — is described in
[Phases](../markers/phases.md#the-full-pipeline).

All directive lines are stripped from the final output.

## Trying it out

Use `repolish preview` with a YAML debug file to experiment without touching
your project. Create a file called `anchor_example.yaml`:

```yaml
template: |
  __version__ = "0.0.0"
  ## repolish-regex[version]: ^__version__\s*=\s*"(.+?)"$

target: |
  __version__ = "1.3.7"
```

Then run:

```bash
repolish preview anchor_example.yaml
```

## Directive naming and uniqueness

Directive names are **global identifiers** across all templates in a run. Two
templates from different providers can each have a `## repolish-start[init]`
block, but the replacement value for `init` is a single string - the later
provider's value wins and the earlier one is silently discarded.

To avoid this, scope names to the file or provider:

```
docker-init       ← instead of just "init"
readme-badges     ← instead of "badges"
mylib-version     ← instead of "version"
```

The same rule applies to regex and multiregex directive names. A regex named
`version` in one template will silently conflict with a `version` directive in
another template that is processed later.

Block anchor replacements come from three places, merged in this order:

1. Provider code - `create_anchors()` return value.
2. Config-level anchors - the `anchors:` mapping in `repolish.yaml` (wins over
   provider code).

Regex and multiregex directives only read from the current project file; they
are not affected by `repolish.yaml` anchors.
