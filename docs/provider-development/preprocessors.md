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

Use keep directives when you want a template to define the overall file shape
but still preserve a developer-edited region if the file already exists.

### Keep a bounded block

This is the best fit for README-style custom sections surrounded by obvious
markers.

```markdown
# repolish/README.md.jinja

## repolish-keep-block[readme-custom-block]: start="<!-- start -->" end="<!-- end -->"

<!-- start -->

Default content for new projects

<!-- end -->
```

If the project file already contains the marker pair, repolish keeps the block
between them. Otherwise the default block stays in place.

When a fixed end marker is not practical, use `end-regex` to close each kept
region dynamically:

```yaml
## repolish-keep-block[provider-additional|after-render]: start="# additional-paths" end-regex="^provider[0-9]+:$"
{% for idx in providers %}
provider{{ idx }}:
  - static{{ idx }}
  # additional-paths
  - default{{ idx }}
{% endfor %}
```

This searches forward from each `start` marker to the first line matching
`end-regex`. If no match appears before the next keep directive (or end of
file), repolish closes the region at that boundary.

If multiple sibling `keep-block` directives in one file reuse the same marker
pair, repolish matches local blocks by encounter order and puts them back in
that same order. One directive is all you need:

```markdown
# repolish/README.md.jinja

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

If the project file already has both marker pairs, each block is preserved in
its own position:

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

Blocks without a matching pair in the project file fall back to the template
default (`_No notes yet._`). There is no need to add a `notes-2` or
`notes-installation` directive variant.

### Keep the rest of the file from a marker onward

Use `keep-rest` for files like `.gitignore`, where the developer owns a tail
section after a sentinel comment.

```gitignore
# repolish/.gitignore.jinja
.venv/
__pycache__/

## repolish-keep-rest[repo-overrides]: marker="## repo-overrides"
## repo-overrides
# Add local overrides below
```

### Keep the header up to a marker

Use `keep-header` when the developer should own the intro/top-of-file preface
and the provider owns the section below the marker.

Place the `keep-header` directive at the very start of the template file. If it
appears later, repolish treats it as invalid and leaves the template content in
place to avoid duplicated prefixes.

```toml
# repolish/pyproject.toml.jinja
## repolish-keep-header[repo-header]: marker="## repolish-managed-start"
Project header text
## repolish-managed-start
Provider-managed settings below
```

The marker text is explicit in the directive so the visible comment style can
match the file type (`#`, `##`, `<!-- -->`, and so on).

Aliases supported in v1:

- `keep-rest` / `keep-the-rest` / `keep-footer`
- `keep-header` / `keep-the-header`

---

## Keeping developer-maintained lists in a structured Python file (keep-block)

Some Python files have a fixed structure that the provider owns, but contain
lists that only a developer can meaningfully fill in — plugin registrations,
feature flag entries, allowed values, and so on. `keep-block` lets the provider
manage the file while leaving those lists entirely up to the developer.

Consider a `registry.py` that the provider ships as part of every project. The
provider controls the imports, the class skeleton, and the module docstring, but
each project registers its own plugins and its own allowed environments:

```python
# repolish/src/{{ project_name }}/registry.py.jinja
"""Plugin registry — managed by repolish, lists owned by the project."""

from __future__ import annotations

from myframework import Plugin, Environment

# repolish-keep-block[plugins]: start="# -- plugins-start" end="# -- plugins-end"
# repolish-keep-block[environments]: start="# -- environments-start" end="# -- environments-end"

# -- plugins-start
PLUGINS: list[type[Plugin]] = []
# -- plugins-end


# -- environments-start
ALLOWED_ENVIRONMENTS: list[str] = ["development", "staging", "production"]
# -- environments-end


def load_plugins() -> None:
    for cls in PLUGINS:
        cls.register()
```

On a fresh project, the template defaults are used as-is. Once developers have
added entries, those two blocks survive every apply unchanged:

```python
# src/myapp/registry.py  (developer's current file)
"""Plugin registry — managed by repolish, lists owned by the project."""

from __future__ import annotations

from myframework import Plugin, Environment

# -- plugins-start
PLUGINS: list[type[Plugin]] = [
    AuthPlugin,
    AuditPlugin,
    MetricsPlugin,
]
# -- plugins-end


# -- environments-start
ALLOWED_ENVIRONMENTS: list[str] = [
    "development",
    "staging",
    "production",
    "demo",
]
# -- environments-end


def load_plugins() -> None:
    for cls in PLUGINS:
        cls.register()
```

The provider can freely change imports, add new methods, rename the module
docstring, or add a third `keep-block` section — none of those changes will
touch `PLUGINS` or `ALLOWED_ENVIRONMENTS`.

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
