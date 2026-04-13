# Templates

Provider templates are plain files (or Jinja2 templates) that repolish stages,
preprocesses, and renders before writing to your project.

## Directory layout

A provider's root directory contains two items repolish cares about:

```
my-provider/
├── repolish.py        ← provider logic
└── repolish/          ← template directory: everything here gets staged
    ├── Makefile
    ├── pyproject.toml
    ├── _repolish.pyproject.poetry.toml   ← conditional variant
    └── .github/
        └── workflows/
            └── ci.yml
```

The `repolish/` subdirectory is copied into the staging area
(`.repolish/_/stage/`). Files outside it — including `repolish.py` — are
provider infrastructure and are never written to your project.

## Jinja2 rendering

Any file can contain Jinja2 expressions. Context fields from your `BaseContext`
subclass are exposed as top-level variables:

```toml
[tool.poetry]
name = "{{ package_name }}"
version = "{{ version }}"
```

Jinja2 rendering is opt-in at the file level — files without any `{{ }}` or
`{% %}` expressions are copied verbatim, so binary files and files with literal
curly braces are safe.

### The `repolish` namespace

The `repolish` namespace is always injected alongside your context fields:

| Variable                          | Type          | Description                         |
| --------------------------------- | ------------- | ----------------------------------- |
| `repolish.repo.owner`             | `str`         | GitHub repository owner             |
| `repolish.repo.name`              | `str`         | GitHub repository name              |
| `repolish.year`                   | `int`         | Current calendar year               |
| `repolish.provider.alias`         | `str`         | Provider alias from `repolish.yaml` |
| `repolish.provider.version`       | `str`         | Provider package version string     |
| `repolish.provider.major_version` | `int \| None` | Integer major version               |
| `repolish.provider.package_name`  | `str`         | Python package name                 |
| `repolish.provider.project_name`  | `str`         | Project/repository name             |

```jinja
# Managed by {{ repolish.provider.alias }} v{{ repolish.provider.version }}
# © {{ repolish.year }} {{ repolish.repo.owner }}/{{ repolish.repo.name }}
```

### `.jinja` extension

Files with a `.jinja` extension are rendered and the extension is stripped from
the output name — useful for syntax highlighting in your editor:

```
repolish/pyproject.toml.jinja  →  pyproject.toml
repolish/Dockerfile.jinja      →  Dockerfile
```

To generate a file that itself ends in `.jinja` (e.g. a Jinja template shipped
inside your project), use a double extension. The outer `.jinja` is the repolish
marker and is stripped; the inner one becomes the output extension:

```
repolish/my-template.jinja.jinja  →  my-template.jinja
```

## Auto-staging

Every file under `repolish/` is **auto-staged**: copied to the project at its
natural relative path on every `repolish apply`, with no extra configuration:

```
repolish/README.md                →  README.md
repolish/pyproject.toml           →  pyproject.toml
repolish/.github/workflows/ci.yml →  .github/workflows/ci.yml
```

Use `create_file_mappings()` only when you need to redirect a template to a
different destination or pick between alternatives at runtime.

## Conditional files and the `_repolish.` prefix

Files whose names start with `_repolish.` are **staging-only** — they are never
auto-staged and only reach the project when explicitly mapped to a destination
by `create_file_mappings()`:

```
repolish/
├── README.md                  # always staged
├── _repolish.ci.github.yml    # only staged when mapped
└── _repolish.ci.gitlab.yml    # only staged when mapped
```

The `_repolish.` prefix has no runtime special meaning. Any file that appears as
a mapping _source_ is excluded from auto-staging regardless of name. The prefix
is a convention that prevents accidental auto-staging at an ugly path and makes
staging-only files easy to spot.

See [File Modes](file-modes.md) for `TemplateMapping`, `FileMode.CREATE_ONLY`,
`FileMode.DELETE`, and extra-context options.

## What never reaches your project

- `_repolish.*` files not selected by any mapping
- Marker lines from preprocessor directives (`## repolish-start[...]`, etc.)
- The `.jinja` extension
- Anything outside `repolish/`

The output in `.repolish/_/render/` is always clean before it is applied.
