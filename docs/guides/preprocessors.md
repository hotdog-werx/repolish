# Preprocessor patterns

This guide shows how to apply preprocessor directives to common real-world
scenarios. For a full explanation of how each directive works, see
[Preprocessors](../how-it-works/preprocessors.md).

## Choosing the right directive

| Situation                                                        | Directive    |
| ---------------------------------------------------------------- | ------------ |
| Preserve a single line value (version, author, URL)              | `regex`      |
| Preserve an entire structured block (tool versions, deps list)   | `multiregex` |
| Let the provider inject dynamic content a developer can override | block anchor |

Default to `regex` and `multiregex` - they live entirely in the template, need
no provider code, and the project file is always the source of truth. Use block
anchors only when the provider (not the project file) should own a section.

---

## Preserving a version string (regex)

The most common use: keep whatever version the developer has in their file
rather than resetting it to the provider default on every apply.

```python
# repolish/src/mylib/__init__.py.jinja
## repolish-regex[version]: ^__version__\s*=\s*"(.+?)"$
__version__ = "0.0.0"
```

If the project file already contains `__version__ = "1.4.2"` the regex captures
`1.4.2` and that line is used in the output. New projects without the file get
the default `"0.0.0"`.

The captured group (inside the parentheses) is what gets substituted. If you
omit the group the entire regex match is used instead.

---

## Preserving versioned tool entries (multiregex)

Tool version files (`mise.toml`, `.tool-versions`, etc.) list many tools whose
versions the developer manages locally. You want to ship sensible defaults but
never clobber versions the developer has already updated.

```toml
# repolish/.mise.toml.jinja
[tools]
## repolish-multiregex-block[tools]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
uv = "0.0.0"
dprint = "0.0.0"
starship = "0.0.0"
```

The block pattern locates the `[tools]` section; the line pattern extracts each
`key = "value"` pair. On apply:

- Keys already present in the project file keep their current values.
- New keys from the template are appended.
- Keys removed from the template are left untouched in the project file
  (repolish does not delete lines it did not put there).

---

## Letting the developer own a section (block anchor)

Use a block anchor when the provider should supply content that a developer can
override for their project, but editing the file directly would not work
(repolish would overwrite it on the next apply).

```dockerfile
# repolish/Dockerfile.jinja
FROM python:3.11-slim

## repolish-start[install]
RUN apt-get update && apt-get install -y build-essential libssl-dev
## repolish-end[install]

COPY pyproject.toml .
RUN pip install --no-cache-dir .
```

The provider can compute the default dynamically:

```python
def create_anchors(self, context: Ctx) -> dict[str, str]:
    packages = ' '.join(context.system_packages)
    return {'install': f'RUN apt-get update && apt-get install -y {packages}'}
```

A developer who needs extra system packages overrides it in `repolish.yaml`:

```yaml
anchors:
  install: |
    RUN apt-get update && apt-get install -y locales libpq-dev
```

Project-level `anchors:` always win over provider code.

---

## Giving developers an append zone (regex tail capture)

A common pattern for files like `.gitignore` or GitHub Actions workflow files:
place a sentinel comment near the end of the template and capture everything
from that comment to the end of the file. Developers can add lines after the
sentinel and they will survive every apply.

```yaml
# repolish/.github/workflows/ci.yaml.jinja
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest

## repolish-regex[additional-jobs]: ^## post-release jobs([\s\S]*)$
## post-release jobs - add your custom jobs here
```

The `[\s\S]*` matches any characters including newlines, so everything the
developer writes after the sentinel comment is captured and reinjected. If no
match is found (e.g. a fresh project) the default line is kept.

The same pattern works in `.gitignore`:

```gitignore
# repolish/.gitignore.jinja
.venv/
__pycache__/
dist/
.repolish/_/

## repolish-regex[project-ignores]: ^## project-specific patterns([\s\S]*)$
## project-specific patterns - add your own below
```

Developers append patterns below the sentinel line; repolish preserves them on
every apply.

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
  [Directive naming and uniqueness](../how-it-works/preprocessors.md#directive-naming-and-uniqueness).
- **Keep default values realistic.** The defaults are what new projects get
  before any local file exists. A semver `"0.0.0"` or a sensible tool version is
  better than an empty string.
- **Use `repolish preview` to test patterns** before running a full apply. See
  [repolish preview](../cli/preview.md).
- **Preprocessing runs before Jinja2.** Values captured from the project file
  are substituted first; Jinja2 expressions in the rest of the template still
  render normally around them.
