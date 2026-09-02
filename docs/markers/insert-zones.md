# Insertion Zones

[Insertions](insertions.md) work in template-rendered files too, but their
`repolish:on:tag` markers always read as foreign machinery dropped into your
document. Insertion zones solve the cosmetic part: the provider declares a
fillable region whose markers are **branded for the content** — a badge row, a
footer, a signature — so the rendered file reads as if it was written that way,
while a provider function still fills the body on every apply.

The template ships a default between the markers; anything undeclared
(overrides, missing function, render failure) keeps that default instead of
failing the file.

## Syntax

```markdown
## repolish:insert[badges] start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"

<!-- generated:badges:on my-org/my-repo style=flat -->

_Default badge row for new projects._

<!-- generated:badges:off -->
```

- `start` / `end` are literal marker strings; `start` matches by **prefix**, so
  the opening marker line may carry arguments
  (`<!-- generated:badges:on my-org/my-repo style=flat -->`).
- `end-regex="..."` replaces `end` for generated closers.
- `function="name"` (optional) names the provider function to call. Without it,
  the zone's tag **is** the function name — `repolish:insert[badges]` looks up
  `badges`, so the common case needs nothing extra. When several providers
  register the same function name, qualify with the provider alias —
  `function="my-provider:badges"` targets that provider's function specifically,
  the same naming rule insertion markers use. Because the provider authors the
  zone into its own template, zones resolve against **every function the
  session's providers contributed** — they are not gated by the per-file
  allowlist `create_file_insertions` applies to developer-authored markers.
- The zone can repeat in one file; every occurrence is filled. The
  [`|after-render` phase](phases.md) is supported for Jinja-generated zones.
- Zones are colon-grammar only — there is no legacy dash spelling. The exact
  zone and marker syntax is on the [Grammar](grammar.md#insertion-zone-grammar)
  page.

!!! tip "Brand the markers"

    `repolish lint` warns (without failing) when literal zone markers lack a
    `generated` / `gen` / `auto` word — branded markers are the entire point.

## Why custom markers at all

Two things set zones apart from plain `repolish:on` blocks, and both follow from
the same root: a zone is **declared by a directive** in a provider template, and
that directive is what carries the phase, the default body, and the marker pair.

- The declaration is what opts a region into the
  [`|after-render` phase](phases.md) — `repolish:on` / `repolish:off` blocks
  have no directive to tag, so they cannot run after rendering.
- Custom markers only make sense because the provider controls both sides and
  the markers always live in the document: the provider declares the zone with a
  directive in the template, writes the marker pair around it, and ships the
  markers (the directive itself strips during rendering) in the rendered file,
  guaranteeing they read as content. A reader never has to recognize the block
  as repolish machinery.

That second point is also the limit:

!!! warning "Do not introduce custom markers in developer-owned files"

    Directives do not exist in developer-owned files, so a zone cannot be
    declared there — hand-writing branded markers in your own file gives
    repolish nothing to fill from. And unlike `repolish:on` / `repolish:off`,
    custom markers carry nothing that says "this is a repolish block": anyone
    editing the file would need knowledge of the function *and* the start/end
    markers to make sense of the region. In developer-owned files the opt-in
    surface is the function alone — use the standard insertion markers, which
    are self-describing.

## Developer control

You tune what the function sees by editing the arguments on the opening marker
line — say, switching `style=flat` to `style=social`. Those edits survive
re-apply: on each run the rendered file re-adopts your opening marker (paired in
occurrence order, like keep blocks) and the body re-fills from your args. The
**body** itself is always regenerated — never hand-edit inside the markers, same
rule as insertions.

Zones participate in `overrides.insertions` like ordinary insertion blocks:
disabling a function or tag leaves the template default in place.

## Fallbacks

The zone body is the provider's promise, but the file must never die over it:

- **no function registered** → the template default stays, a diagnostic is
  reported.
- **function raises** → the template default stays (unlike insertion blocks,
  which empty the body); diagnostic reported.
- **disabled via config** → the template default stays; counted as disabled in
  the insertion report.

## Provider side

```python
def create_file_insertions(self, context):
    def badges(*args):
        owner_repo = args[0] if args else 'unknown/unknown'
        style = next((a.split('=', 1)[1] for a in args if a.startswith('style=')), 'flat')
        return render_badges(owner_repo, style=style)

    return {'README.md': {'badges': badges}}
```

The destination file does **not** have to appear in this mapping (or in a
list-mode allowlist) for the zone to fill — registering the function anywhere is
enough, since the provider already chose it by declaring the zone. The mapping
only gates developer-authored `repolish:on` markers.

The function receives the opening marker's arguments the same way an insertion
function receives marker args (shlex-split, `-->` stripped); the usual signature
forms apply — `*args`, positional params, or a single `InsertionBlock` parameter
for full metadata.
