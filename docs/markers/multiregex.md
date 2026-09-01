# Multiregex

Multiregex was born from regex fatigue: one [`repolish:regex`](regex.md) per
line didn't scale. Instead of a pattern per line, you write **two patterns
once** — one to locate a block, one to read key/value pairs out of it — and
every matching line in that block is covered.

The design contract, straight from the mise.toml case that motivated it: **the
provider owns the set of keys, the developer owns the values.** The provider
decides which tools the project needs — that part is final — while you keep
whatever versions you need, whether pinned against a bug or bumped deliberately.

<!-- Align with: tests/directives/multiregex/, tests/integration/test_directives_after_render.py; examples validated with repolish preview -->

## Syntax

A multiregex directive is a **pair of markers sharing one tag**:

```toml
[tools]
## repolish:multiregex-block[tools] ^\[tools\](.*?)(?=\n\[|\Z)
## repolish:multiregex[tools] ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
uv = "0.0.0"
dprint = "0.0.0"
```

- **`repolish:multiregex-block[tag]`** — the block pattern. It runs against
  **your current file**; its first capture group is the block body to read
  (everything between `[tools]` and the next section header here).
- **`repolish:multiregex[tag]`** — the line pattern. It extracts key/value pairs
  from that body. The canonical shape is `^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$`
  — `key = "value"` lines, key in group 2, value in group 4.
- The template keeps a real `[tools]` section with default values. The section
  header's name must equal the tag (`[tools]` ↔ tag `tools`).
- Both directive lines are stripped on a successful pass. Supports the
  [`|after-render` phase](phases.md) — including for values assembled from
  context, see the [worked example](phases.md#worked-example).

## Worked example

=== "Template"

    `repolish/mise.toml.jinja` — the provider ships tool defaults:

    ```toml
    [tools]
    ## repolish:multiregex-block[tools] ^\[tools\](.*?)(?=\n\[|\Z)
    ## repolish:multiregex[tools] ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
    uv = "0.0.0"
    dprint = "0.0.0"
    starship = "0.0.0"
    ```

=== "Your file"

    `mise.toml` — versions you already chose:

    ```toml
    [tools]
    uv = "0.9.1"
    dprint = "0.50.2"
    ```

=== "Try it"

    Save this as `scratch.yaml`:

    ```yaml
    template: |
      [tools]
      ## repolish:multiregex-block[tools] ^\[tools\](.*?)(?=\n\[|\Z)
      ## repolish:multiregex[tools] ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
      uv = "0.0.0"
      dprint = "0.0.0"
      starship = "0.0.0"

    target: |
      [tools]
      uv = "0.9.1"
      dprint = "0.50.2"
    ```

    and run:

    ```bash
    repolish preview scratch.yaml
    ```

=== "Result"

    Your versions survive; a tool the provider adds later (`starship`)
    appears at its default until you pin it — on every apply:

    ```toml
    [tools]
    uv = "0.9.1"
    dprint = "0.50.2"
    starship = "0.0.0"
    ```

## Ownership contract

Because the output section is rebuilt from the template:

- **Values for known keys are yours.** `uv = "0.9.1"` stays `0.9.1` no matter
  how the provider restructures the file.
- **New provider keys appear at their defaults** — nothing to migrate.
- **Keys you add that the provider doesn't declare are removed** on the next
  apply. The provider's key set is final _for the managed section_. (Earlier
  docs claimed local additions survive — they don't; the corrected behavior here
  is preview-verified.) To add your own tools, own a tail region instead — see
  below.

### Adding your own: own the tail

A managed section and a developer-owned tail compose cleanly. This is the
lineage of the keep family, by the way: the tail-capture regex
(`^## sentinel[^\n]*\n([\s\S]*)$`, see the
[trim safeguard](regex.md#the-trim-safeguard)) was the original way to say
"everything past this point is mine" — and `keep-rest` is its painless
descendant:

```toml title="repolish/mise.toml.jinja"
[tools]
## repolish:multiregex-block[tools] ^\[tools\](.*?)(?=\n\[|\Z)
## repolish:multiregex[tools] ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
uv = "0.0.0"
dprint = "0.0.0"

## repolish:keep-rest[extra-tools] marker="## local tools"
## local tools
# add your own tools below
```

Anything after the `## local tools` marker is yours outright, so a project with
`jq = "1.7.1"` and `yq = "4.44"` under it keeps them on every apply — with the
multiregex section above still preserving your `uv`/`dprint` versions (validated
with `repolish preview`). Details in [Keep the Rest](keep-rest.md).

## Whole-file fallback

If the template has no `[tag]` section header at all, the extracted values are
applied to every matching `key = "value"` line anywhere in the file. Prefer the
section form — the fallback trades precision for convenience.

## Quirks and limits

- **No local block ⇒ directive lines leak.** When the block pattern matches
  nothing in your file (including a fresh project), nothing is replaced _and the
  directive lines survive into the output_. A fix is tracked in the
  [uncovered regions](index.md#what-markers-dont-cover-yet) map.
- **First block only.** Only the first block match in your file is read —
  repeated sections are part of the same single-occurrence gap as regex.
- **Preserving a region, not values?** Use [keep blocks](keep-block.md) instead
  — no patterns, and the developer owns the region outright.
