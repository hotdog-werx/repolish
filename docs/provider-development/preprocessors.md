# Preprocessor patterns

This guide shows how to apply preprocessor directives to common real-world
scenarios. For a full explanation of how each directive works, see
[Preprocessors](../concepts/preprocessors.md).

## Two-phase directives

Directives run in the `pre-render` phase by default. Use the `|after-render`
suffix when a directive appears inside Jinja-generated content (for example
loops), so repolish evaluates it on the rendered file instead — see
[Phases](../markers/phases.md) for the syntax, supported families, and the full
pipeline.

## Choosing the right directive

| Situation                                                        | Directive    |
| ---------------------------------------------------------------- | ------------ |
| Preserve a single line value (version, author, URL)              | `regex`      |
| Preserve an entire structured block (tool versions, deps list)   | `multiregex` |
| Let the provider inject dynamic content a developer can override | block anchor |
| Preserve a developer-owned zone in a provider-managed file       | keep blocks  |

Default to `regex` and `multiregex` - they live entirely in the template, need
no provider code, and the project file is always the source of truth. Use block
anchors only when the provider (not the project file) should own a section. Use
keep blocks when the provider should define the file shape but a project owner
should be able to keep a visible region intact across applies.

---

## Preserving a version string (regex)

The most common use: keep whatever version the developer has in their file
rather than resetting it to the provider default on every apply. Syntax,
capture-group rules, and the two-sided contract are covered in
[Regex](../markers/regex.md).

---

## Preserving versioned tool entries (multiregex)

Tool version files (`mise.toml`, `.tool-versions`, etc.) list many tools whose
versions the developer manages locally. Ship sensible defaults without
clobbering versions the developer has already pinned. Syntax, the pair of
patterns, and the ownership contract (your values survive for provider-declared
keys; locally-added keys do not) are covered in
[Multiregex](../markers/multiregex.md).

---

## Letting the developer own a section (block anchor)

Use a tag block when the provider should supply content that a developer can
override for their project, but editing the file directly would not work
(repolish would overwrite it on the next apply). Syntax, content sources, and
override precedence are covered in
[Tag Blocks & Anchors](../markers/tag-blocks.md).

---

## Keeping a visible zone intact (keep directives)

For developer-owned regions inside provider-managed files, reach for keep
directives instead of hand-written tail-capture regexes — the visible marker
lines document the intention. Pages and examples:

- [Keep Blocks](../markers/keep-block.md) — bounded `start`/`end` regions,
  repeated blocks (first-to-first pairing), `end-regex` for Jinja-generated
  loops, and the directive-placement rule (each keep-block directive directly
  above its own region; stacked directive lines leave earlier regions
  unmanaged). Includes the registry.py-style example with corrected placement.
- [Keep the Rest](../markers/keep-rest.md) — everything from a marker to EOF.
- [Keep the Header](../markers/keep-header.md) — top of file up to a marker;
  the directive must be the template's first line.

---

## Giving developers an append zone (regex tail capture)

A sentinel comment near the end of the template with a tail-capturing regex
preserves whatever the developer appends after it. The working pattern
(including an indentation-trim subtlety that a naive `([\s\S]*)$` capture runs
into with column-0 entries) is covered in
[Regex → the trim safeguard](../markers/regex.md#the-trim-safeguard).

---

## Combining directives (pyproject.toml)

A single template can mix regex and anchor directives to handle different parts
of the file independently.

```toml
# repolish/pyproject.toml.jinja
[project]
name = "{{ project_name }}"
## repolish-regex[version]: ^version\s*=\s*"(.+?)"$
version = "0.1.0"

## repolish-start[optional-deps]
# no optional dependencies by default
## repolish-end[optional-deps]
```

The regex keeps the version the developer has already bumped. The anchor lets
the provider (or the developer via `repolish.yaml`) inject optional dependency
groups without touching the rest of the file.

---

## Tips

- **Name directives to their scope.** `docker-install` is safer than `install`
  because directive names are global - two providers accidentally using the same
  name will conflict silently. See
  [Directive naming and uniqueness](../concepts/preprocessors.md#directive-naming-and-uniqueness).
- **Keep default values realistic.** The defaults are what new projects get
  before any local file exists. A semver `"0.0.0"` or a sensible tool version is
  better than an empty string.
- **Use `repolish preview` to test patterns** before running a full apply. See
  [repolish preview](../reference/preview.md).
- **Preprocessing runs before Jinja2.** Values captured from the project file
  are substituted first; Jinja2 expressions in the rest of the template still
  render normally around them.
