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

## Mode overlay directories

When a provider runs in a monorepo, repolish stages a mode-specific overlay
directory **after** the base `repolish/` templates. The overlay directory is a
sibling of `repolish/` named after the current mode — `root/`, `member/`, or
`standalone/`:

```
my-provider/
├── repolish.py
├── repolish/                  ← base templates (all modes)
│   ├── pyproject.toml
│   └── README.md
├── root/                      ← overlay for root sessions
│   └── pyproject.toml         ← replaces repolish/pyproject.toml in root mode
└── member/                    ← overlay for member sessions
    └── pyproject.toml         ← replaces repolish/pyproject.toml in member mode
```

Overlay files replace base files at the same relative path. If
`root/pyproject.toml` exists and the session mode is `root`, it replaces
`repolish/pyproject.toml` in the staging tree. Files in the base directory that
have no overlay counterpart are staged normally.

This is a file-level alternative to branching inside `create_file_mappings()`.
Use overlays when the template content itself differs across modes; use
`create_file_mappings()` when the _destination path_ differs.

`ModeHandler.templates_root` points to the overlay directory for the current
mode, so handlers can discover mode-specific templates dynamically with
`self.templates_root.glob(...)`. See
[Mode Handlers](../provider-development/mode-handler.md) for details.

## Conditional files and the `_repolish.` prefix

Any path component that starts with `_repolish.` makes the whole entry
**staging-only** — it is never auto-staged and only reaches the project when
explicitly mapped to a destination by `create_file_mappings()`.

**File prefix** — the traditional form for single-file conditionals:

```
repolish/
├── README.md                  # always staged
├── _repolish.ci.github.yml    # only staged when mapped
└── _repolish.ci.gitlab.yml    # only staged when mapped
```

**Folder prefix** — use a `_repolish.`-prefixed directory when a whole subtree
of files belongs to one conditional variant. Files inside mirror the destination
structure relative to the target directory:

```
repolish/
├── README.md
├── _repolish.ci.github/          # only staged when any file inside is mapped
│   ├── workflows/                # mirrors .github/workflows/
│   │   └── ci.yml
│   └── dependabot.yml
└── _repolish.ci.gitlab/
    └── .gitlab-ci.yml
```

Each file's path inside the folder is relative to the destination directory. Use
`map_folder` to build the dict automatically:

```python
from repolish import BaseContext, BaseInputs, Provider, map_folder

class Ctx(BaseContext):
    use_github: bool = True

class MyProvider(Provider[Ctx, BaseInputs]):
    def create_file_mappings(self, context: Ctx):
        tpl = self.templates_root / 'repolish'
        if context.use_github:
            github_files = map_folder('.github', '_repolish.ci.github', tpl)
            return {
                **github_files,
                'README.md': '_repolish.readme.github.md',
            }
        gitlab_files = map_folder('', '_repolish.ci.gitlab', tpl)
        return {
            **gitlab_files,
            'README.md': '_repolish.readme.gitlab.md',
        }
```

Assigning to a variable first lets you inspect the contents before returning —
useful for debugging. See the `map_folder` reference for the `file_mode` and
`extra_context` options.

The `_repolish.` prefix has no runtime special meaning — it is a convention that
prevents accidental auto-staging and makes conditional material easy to spot.
Any file whose path contains a `_repolish.`-prefixed component is treated as
conditional; that check covers both the file prefix and the folder prefix.

See [File Modes](file-modes.md) for `TemplateMapping`, `FileMode.CREATE_ONLY`,
`FileMode.DELETE`, and extra-context options.

## What never reaches your project

- `_repolish.*` files and files inside `_repolish.`-prefixed folders not
  selected by any mapping
- Marker lines from preprocessor directives (`## repolish-start[...]`, etc.)
- The `.jinja` extension
- Anything outside `repolish/`

The output in `.repolish/_/render/` is always clean before it is applied.
