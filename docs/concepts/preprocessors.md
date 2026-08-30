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
[Regex](../markers/regex.md), including the two-sided contract (the pattern must
match the template default too) and the indentation trim safeguard.

## Multiregex directives

Multiregex directives — a block/line pattern pair that keeps your values for a
structured section like `[tools]` — are covered in
[Multiregex](../markers/multiregex.md), including the ownership contract (the
provider owns the key set, you own the values).

## Block anchors

Tag blocks — `repolish-start[name]` … `repolish-end[name]` pairs filled by
provider-supplied anchor content — are covered in
[Tag Blocks & Anchors](../markers/tag-blocks.md).

## Keep directives

Keep directives name developer-owned regions inside provider-managed files —
no regex to write, and the visible markers document the intention. Each variant
is covered in the Markers tab:

- [Keep Blocks](../markers/keep-block.md) — a bounded `start`/`end` region
  (with `end-regex` for Jinja-generated loops).
- [Keep the Rest](../markers/keep-rest.md) — everything from a marker to EOF.
- [Keep the Header](../markers/keep-header.md) — the top of the file up to a
  marker.

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

**Anchor** names are global identifiers across all templates in a run: two
templates from different providers can each use a `## repolish-start[init]`
block, but `init` resolves to a single replacement string - the later
provider's value wins and the earlier one is silently discarded. Namespace
anchor names per provider (`docker-init` instead of `init`) — see
[Tag Blocks & Anchors](../markers/tag-blocks.md#naming).

Regex, multiregex, and keep directive names are scoped to the template file
they appear in; the same name in two different files does not conflict.
