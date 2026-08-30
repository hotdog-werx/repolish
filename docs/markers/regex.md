# Regex

Regex directives came after anchors and flipped the relationship: instead of the
provider owning what a region says, **the project file is the source of truth**.
A regex directive is a contract — "the provider promises to respect whatever
text in your file matches this pattern." You edit the final document directly;
no detour through `repolish.yaml`.

The classic cases are values repolish can't know: a `description = "..."` line
only the project can write, a `version` that other tools bump between applies.

The honest tradeoff: writing the pattern is the painful part. That's why
[`repolish preview`](../reference/preview.md) exists — an interactive debugging
session over a single template, no project setup required. Every example on this
page was validated with it.

<!-- Align with: tests/directives/test_processors.py (regex cases), tests/integration/test_directives_after_render.py; docs examples here validated with repolish preview -->

## Syntax

```python
## repolish-regex[version]: ^__version__\s*=\s*"(.+?)"$
__version__ = "0.0.0"
```

- The directive line sits directly above the line it manages and is always
  stripped from the output.
- If the pattern has a **capture group**, the first group is the preserved
  value; with no group, the entire match is used. Prefer explicit groups.
- On apply, the pattern runs against **your current file**. If it matches, the
  captured text replaces the match in the template; if not, the template default
  ships unchanged.
- Supports the [`|after-render` phase](phases.md) — necessary when the line the
  directive manages is produced by Jinja (loops, conditionals).

## Worked example

Preserving `version` and `description` in a provider-managed `pyproject.toml`:

=== "Template"

    `repolish/pyproject.toml.jinja`:

    ```toml
    [project]
    name = "mylib"
    ## repolish-regex[version]: ^version\s*=\s*"(.+?)"$
    version = "0.0.0"
    ## repolish-regex[description]: ^description\s*=\s*"(.*?)"$
    description = ""
    ```

=== "Your file"

    `pyproject.toml` — values you (or your tooling) already set:

    ```toml
    [project]
    name = "mylib"
    version = "1.4.2"
    description = "A library for things"
    ```

=== "Try it"

    Save this as `scratch.yaml`:

    ```yaml
    template: |
      [project]
      name = "mylib"
      ## repolish-regex[version]: ^version\s*=\s*"(.+?)"$
      version = "0.0.0"
      ## repolish-regex[description]: ^description\s*=\s*"(.*?)"$
      description = ""

    target: |
      [project]
      name = "mylib"
      version = "1.4.2"
      description = "A library for things"
    ```

    and run:

    ```bash
    repolish preview scratch.yaml
    ```

=== "Result"

    The provider can restructure the rest of the file freely; these two lines
    stay yours, on every apply:

    ```toml
    [project]
    name = "mylib"
    version = "1.4.2"
    description = "A library for things"
    ```

## The contract is two-sided

The pattern must match **both** files: your current file (to capture from) and
the template itself (to find the region to replace). A pattern that doesn't
match the template's own default silently falls back to that default.

The subtle instance: `"(.+?)"` requires at least one character between the
quotes, so it cannot match the template default `description = ""` — the
directive above therefore uses `"(.*?)"`. `repolish preview` surfaces this
instantly (a `regex_matched_in_target` event with unchanged output is the tell);
a full `apply` would leave you guessing.

## The trim safeguard

As a conservative guard, repolish trims a captured block to the contiguous
same-indentation region — this stops a greedy multiline pattern from pulling the
next section of the file into the capture. When in doubt, tighten the pattern
instead of relying on the guard.

The guard has one real surprise, found while validating this very page with
`preview`. For an append-zone directive like:

```yaml
## repolish-regex[project-ignores]: ^## project-specific patterns[^\n]*\n([\s\S]*)$
## project-specific patterns - add your own below
```

the `[^\n]*\n` before the capture group matters: it makes the capture **start
after the sentinel line's newline**, so its first line is your appended content
at column 0 and the trim guard keeps it. If the capture starts mid-sentinel
(`^## project-specific patterns([\s\S]*)$`), the sentinel's trailing text
anchors the indentation and column-0 entries get trimmed away — the directive
appears to do nothing. (Indented content, like extra YAML keys under a sentinel,
survives either way.)

## Iterating with preview

Write a small YAML debug file and run it until the pattern does what you mean:

```yaml title="scratch.yaml"
template: |
  ## repolish-regex[version]: ^version\s*=\s*"(.+?)"$
  version = "0.0.0"

target: |
  version = "1.4.2"
```

```bash
repolish preview scratch.yaml
repolish preview scratch.yaml --show-patterns --show-steps -vv
```

`--show-steps -vv` shows each family's pass and which regexes matched, with the
captured values — the fastest feedback loop for directive work. Full format in
[repolish preview](../reference/preview.md).

<!-- insertion-candidate: the debug-file examples here could be rendered from tests (or preview fixtures) once providers dogfood insertions -->

## Limits

Regex adoption is **single-occurrence**: with loop-generated duplicates only the
first rendered line is reconciled against your file. When you find yourself
preserving a _region_ rather than a value, [keep blocks](keep-block.md) are the
better tool — no pattern to write, and occurrence pairing is handled for you.
See the [uncovered regions](index.md#what-markers-dont-cover-yet) map for the
planned follow-ups.
