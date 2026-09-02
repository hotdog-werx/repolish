# Grammar

The exact marker syntax, in one place. The family pages explain what each marker
_does_; this page defines what the parser accepts.

Two marker families exist:

- **Directives** — lines in _template_ files, processed around rendering.
- **Insertions** — marker blocks in any file, filled after files are written.

## Directive grammar

```text
<anything> repolish:<command>[<tag>] <payload>
<anything> repolish:<command>[<tag>|<phase>] <payload>
```

- One directive per line. The marker is recognized anywhere on the line, so any
  comment style works (`##`, `#`, `//`, `<!-- ... -->`), and text before or
  after the marker is ignored.
- The namespace separator is a colon: `repolish:<command>`. The legacy dash
  spelling (`repolish-<command>`) is still accepted for the pre-existing
  families with a deprecation warning, and will be removed in v2 — never write
  it in new templates.
- The tag is required, non-empty, and may contain any characters except `]`.
  Directive names are what diagnostics, warnings, and pairing rules refer to.
- The phase suffix lives inside the brackets: `[name|after-render]`. Without a
  suffix the directive runs pre-render. An unknown suffix warns and falls back
  to pre-render — see [Phases](phases.md).
- The payload is separated from `]` by whitespace. A colon between `]` and the
  payload (`regex[name]: <pattern>`) is accepted for legacy compatibility; don't
  write it in new templates.
- `key="value"` payloads are double-quoted with backslash escapes
  (`start="a \"b\" c"`). Bare-pattern payloads are the rest of the line, trimmed
  — no quoting.

Payload per command:

| Directive                               | Payload                                                       |
| --------------------------------------- | ------------------------------------------------------------- |
| `repolish:start[n]` … `repolish:end[n]` | none — the pair marks a block                                 |
| `repolish:regex[n]`                     | `<pattern>` (rest of line)                                    |
| `repolish:multiregex-block[n]`          | `<pattern>` (rest of line)                                    |
| `repolish:multiregex[n]`                | `<pattern>` (rest of line)                                    |
| `repolish:keep-block[n]`                | `start="..." end="..."` or `start="..." end-regex="..."`      |
| `repolish:keep-rest[n]`                 | `marker="..."` (aliases: `keep-the-rest`, `keep-footer`)      |
| `repolish:keep-header[n]`               | `marker="..."` (alias: `keep-the-header`)                     |
| `repolish:insert[n]`                    | `start="..." end="..." [function="..."]` or `end-regex="..."` |

For `keep-block` and `insert` the argument order is fixed: `start` first, then
`end`/`end-regex`, then the optional `function`. `repolish:insert` is colon-only
— it has no dash spelling, and the post-bracket colon is not accepted.

All directive lines are stripped from the output at the phase that processes
them; a line the grammar doesn't recognize is not a directive and passes through
into the rendered file.

## Insertion marker grammar

```text
repolish:on[:tag] [function] [args...]
repolish:off[:tag]
```

A block is an `on` marker, a body, and a matching `off` marker, wrapped in any
of four comment styles:

```html title="HTML — may appear anywhere, including mid-line"
<!-- repolish:on:config config-options brief=yes -->
...
<!-- repolish:off:config -->
```

```bash title="Line comments — the marker must be the whole line"
# repolish:on:config config-options
...
# repolish:off:config

// repolish:on:config config-options
...
// repolish:off:config

/* repolish:on:config config-options */
...
/* repolish:off:config */
```

- `#`, `//`, and `/* ... */` markers must occupy the full line (leading
  whitespace allowed). HTML markers are not line-anchored.
- The **tag pairs** the `on`/`off` markers. It's optional — tag-less blocks pair
  with each other — but a tag can only be open once at a time; a second `on`
  with the same tag before its `off` is a parse diagnostic. Using distinct tags
  keeps blocks self-describing and is what the
  [adoption rules](insertions.md#editing-the-block) match on.
- The colon belongs to the tag and is optional with it — a block can omit both,
  letting the function follow `repolish:on` directly (a _tag-less_ block).
  Beware: a single token with no colon is parsed as a tag with no function, not
  as a function. Write the `repolish:on:tag function` form.
- The payload is split shell-style (quotes group words: `style="for the badge"`
  is one argument). The first token is the function name, the rest are passed to
  it as string arguments. An unterminated quote is a parse diagnostic, not a
  crash.
- **Function names** resolve against the file's function registry. When several
  providers register functions for one file, qualify with the provider alias —
  `alpha:display-year` targets that provider's function specifically; an
  unqualified name resolves deterministically from the active provider order.
- The body is always regenerated; parse failures (unclosed marker, `off` without
  `on`, malformed arguments) are reported as diagnostics and never fail the
  apply.

## Insertion zone grammar

A zone is declared by a directive and filled by the insertion phase:

```text
## repolish:insert[name] start="<opening-prefix>" end="<closer>" [function="fn"]

<opening-prefix> <args...>
template default
<closer>
```

- `start` matches the opening marker line by **prefix**, so the opening line may
  carry arguments after it; they are split shell-style and passed to the
  function. A trailing `-->` (comment close) is not part of the arguments.
- `end="..."` matches the closing line literally; `end-regex="..."` matches it
  by regular expression. An `end-regex` that matches nothing means no region —
  the template default stays.
- The template default is the fallback for every fill failure: unknown, failing,
  or configuration-disabled function. See
  [Insertion zones](insert-zones.md#fallbacks).
- Brand zone markers with a `generated` / `gen` / `auto` word; `repolish lint`
  warns (without failing) when literal markers don't.

## Diagnostics at a glance

Malformed markers never crash an apply — they warn and fall back:

| Situation                                    | Effect                                             |
| -------------------------------------------- | -------------------------------------------------- |
| Legacy dash spelling (`repolish-regex[n]`)   | deprecation warning, still processed (until v2)    |
| Unknown `\|phase` suffix                     | warning, directive treated as pre-render           |
| Directive line the grammar doesn't recognize | not a directive — passes through into output       |
| Insertion `off` without `on` / unclosed `on` | parse diagnostic, block skipped                    |
| Insertion `on` with an already-open tag      | parse diagnostic, second block skipped             |
| Unknown insertion function                   | diagnostic, block counted as failed in the summary |
| Zone function unknown / raises / disabled    | diagnostic, template default kept                  |
| Zone `end-regex` matches nothing             | no region found, template default kept             |

For behavior rather than syntax — what each marker _does_ — see the family
pages: [tag blocks](tag-blocks.md), [regex](regex.md),
[multiregex](multiregex.md), [keep blocks](keep-block.md),
[keep the rest](keep-rest.md), [keep the header](keep-header.md),
[insertions](insertions.md), [insertion zones](insert-zones.md).
