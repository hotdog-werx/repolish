# Preprocessors

Repolish uses preprocessor directives embedded directly in template files.
Before Jinja2 runs, repolish reads these directives, captures values from your
existing project file, and injects them back so local state survives every
apply. All directive lines are stripped from the final output.

Regex and multiregex directives are the primary mechanism - they are
self-contained in the template, require no provider code, and read from the
project file automatically. Block anchors are a simpler option for cases where
the provider (not the project file) controls a section.

## Regex Replacements

Regex directives preserve individual values - versions, config entries, author
fields - by matching them in your existing file.

### Syntax

```
## repolish-regex[name]: pattern
default_value
```

### Usage

The pattern runs against the current project file. If a match is found, the
captured group (or full match if no group) replaces the template line. If no
match is found, the default line is kept.

**Example:**

```python
# Template
## repolish-regex[version]: __version__ = "(.+?)"
__version__ = "0.0.0"

# Target file contains: __version__ = "1.2.3"
```

**Result:**

```python
__version__ = "1.2.3"
```

## Multiregex Replacements

Multiregex directives handle structured blocks - a `[tools]` section in TOML, a
`requirements` list - preserving locally pinned values while allowing the
provider to add new keys.

### Syntax

```ini
## repolish-multiregex-block[block-name]: block_pattern
## repolish-multiregex[block-name]: item_pattern
key1 = "default1"
key2 = "default2"
key3 = "default3"
```

### Usage

The `multiregex-block` pattern locates the entire section in the project file.
The `multiregex` pattern extracts individual key-value pairs within it. Existing
values are preserved for matching keys; new provider keys are appended.

**Example:**

```ini
# Template
[tools]
## repolish-multiregex-block[tools]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
uv = "0.0.0"
dprint = "0.0.0"
starship = "0.0.0"

# Target file contains:
[tools]
uv = "0.7.20"
dprint = "0.50.1"
starship = "1.0.0"
```

**Result:**

```ini
[tools]
uv = "0.7.20"
dprint = "0.50.1"
starship = "1.0.0"
```

## Block Anchors

Block anchors mark a section in the template whose content is supplied by the
provider's `create_anchors()` method (which can generate content dynamically
from context) or by an `anchors:` mapping in `repolish.yaml` (project-level
overrides win). If no replacement is provided, the default content between the
markers is kept. All marker lines are stripped - the final project file is
clean.

The tradeoff compared to regex directives: to customise the injected content you
set it in `repolish.yaml`, because editing the file directly won't stick - the
next apply will overwrite it with whatever the provider computes. Regex and
multiregex directives avoid this by reading from the file itself, so the file is
always the source of truth.

### Syntax

```
## repolish-start[anchor-name]

Default content goes here

## repolish-end[anchor-name]
```

### Usage

Block anchors are replaced with content from the provider's `create_anchors()`
return value or the project's `anchors:` key in `repolish.yaml`, keyed by anchor
name. If no replacement is provided for a key, the default content between the
markers is preserved.

**Example:**

```yaml
# Template
## repolish-start[header]
# Default Header
Welcome to our project!
## repolish-end[header]

# Context
header: |
  # Custom Header
  Welcome to My Awesome Project!
```

**Result:**

```markdown
# Custom Header

Welcome to My Awesome Project!
```

## Processing Order

Preprocessors are applied in the following order:

1. **Block anchors** - replacement from provider code or config
2. **Regex directives** - capture from the current project file
3. **Multiregex directives** - structured block capture from the current project
   file

## Best Practices

- Prefer regex and multiregex directives - they live in the template file itself
  and require no extra provider code.
- Use descriptive names that clearly indicate their purpose (e.g.
  `tools-versions`, `version-string`).
- Test your regex patterns thoroughly to ensure they match the expected content.
- Keep default values in templates so they work correctly for new projects where
  no existing file exists yet.
- Use block anchors only when the provider (not the project) should control the
  section content.
- Use the debugger (`repolish preview`) to validate your preprocessor patterns.

## Practical examples

### Dockerfile (block anchor)

Template (`templates/my-template/repolish/Dockerfile`):

```dockerfile
FROM python:3.11-slim

## repolish-start[install]
# install system deps
RUN apt-get update && apt-get install -y build-essential libssl-dev
## repolish-end[install]

COPY pyproject.toml .
RUN pip install --no-cache-dir .
```

Local project `Dockerfile` (developer has custom install needs):

```dockerfile
FROM python:3.11-slim

## repolish-start[install]
# custom build deps for project X
RUN apt-get update && apt-get install -y locales libpq-dev
## repolish-end[install]

COPY pyproject.toml .
RUN pip install --no-cache-dir .
```

When Repolish preprocesses the template, the `install` block from the local
project file is preserved in the staged template. The generated output keeps the
local custom `RUN` command while the rest of the Dockerfile comes from the
template.

### pyproject.toml (regex directive + block anchor)

Template (`templates/my-template/repolish/pyproject.toml`):

```toml
[tool.poetry]
name = "{{ cookiecutter.package_name }}"
version = "0.1.0"
## repolish-regex[keep]: ^version\s*=\s*".*"

description = "A short description"

## repolish-start[extra-deps]
# optional extra deps (preserved when present)
## repolish-end[extra-deps]
```

Local `pyproject.toml` (developer bumped version and added extras):

```toml
[tool.poetry]
name = "myproj"
version = "0.2.0"

description = "Local project description"

## repolish-start[extra-deps]
requests = "^2.30"
## repolish-end[extra-deps]
```

The `repolish-regex[keep]` directive ensures the local `version = "0.2.0"` line
is preserved instead of being replaced by the template's `0.1.0`. The
`extra-deps` block is preserved whole-cloth, letting projects keep local
dependency additions.

**Tips**

- Use meaningful names (`install`, `readme`, `extra-deps`) so reviewers
  immediately understand what the preserved section contains.
- Regex directives are applied line-by-line; prefer simple, easy-to-read
  patterns to avoid surprises.
- Preprocessing runs before Jinja2 rendering, so template substitutions still
  work around preserved sections.

## Regex capture groups

Two important behaviors control what is extracted and inserted:

**Capture group preference**: If your regex includes a capturing group
(parentheses), Repolish prefers the first capture group (group 1) as the block
to insert into the template. If there are no capture groups, Repolish falls back
to the entire match (group 0).

**Safeguard trimming**: As a conservative safeguard Repolish trims the captured
block to a contiguous region based on indentation, so that incidental following
sections are not accidentally pulled in. The canonical way to express intent is
an explicit capture group - authors should prefer to capture exactly what they
mean.

### Example

Template excerpt:

```toml
cat1:
  - line1
  - line2
  ## repolish-regex[cat1-filter]: (^\s*# cat1-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat1-filter-additional-paths

cat2:
  - from-template
  ## repolish-regex[cat2-filter]: (^\s*# cat2-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat2-filter-additional-paths
```

Local file excerpt:

```toml
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra

cat2:
  - from-template
```

Result after preprocessing:

```toml
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra

cat2:
  - from-template
  # cat2-filter-additional-paths
```

When your regex is too greedy, tighten it or add explicit parentheses around the
intended capture so Repolish can reliably hydrate the template.

## Directive scope and uniqueness

Directive names are **global identifiers** across all templates in a session.
For block anchors specifically, replacements can come from three places, merged
in this order:

1. **Provider templates**: any `## repolish-start[...]` /
   `## repolish-regex[...]` markers present inside provider template files.
2. **Provider code**: a provider's `create_anchors()` callable can return a
   mapping (key → replacement text) used during preprocessing.
3. **Config-level anchors**: the `anchors` mapping in `repolish.yaml` applies
   last and overrides earlier values.

Directive (and anchor) keys must be unique across the entire merged template
set. If two template files from different providers use the same name, the later
provider's value wins, which can produce surprising results.

### Example conflict

Two providers accidentally use the same key `init`:

- `templates/a/Dockerfile` contains `## repolish-start[init]` …
  `## repolish-end[init]`
- `templates/b/README.md` also contains `## repolish-start[init]` …
  `## repolish-end[init]`

The `init` block from whichever provider is processed last will replace the
other. For predictable behavior, scope names to the file or provider: e.g.
`docker-install` or `readme-intro`.

**Best practice**: prefix directive names with the file or provider name when
the content is file-scoped. This avoids accidental collisions when multiple
providers contribute templates with similarly-named sections.
