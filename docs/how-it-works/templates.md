# Templates

Provider templates are plain files (or Jinja2 templates) that repolish stages,
preprocesses, and renders before writing to your project.

## Directory layout

Every provider stores its templates under `templates/repolish/` relative to
the provider root:

```
my-provider/
├── repolish.py
└── templates/
    └── repolish/           ← everything here gets staged
        ├── Makefile
        ├── pyproject.toml
        ├── _repolish.pyproject.poetry.toml   ← conditional variant
        └── .github/
            └── workflows/
                └── ci.yml
```

The `repolish/` subdirectory is what repolish copies into the staging area
(`.repolish/_/stage/`). Files outside it are provider infrastructure and are
never written to your project.

## Jinja2 rendering

Any file can contain Jinja2 expressions. Context variables come from the merged
provider context and are available by name:

```toml
[tool.poetry]
name = "{{ package_name }}"
python_requires = ">={% raw %}{{{% endraw %} python_version {% raw %}}}{% endraw %}"
```

The special `repolish` namespace is always available and provides
repository-level metadata:

```toml
# {{ repolish.repo.owner }}/{{ repolish.repo.name }}
```

Jinja2 rendering is opt-in at the file level — files without any `{{ }}` or
`{% %}` expressions are copied verbatim, so binary files and files with literal
curly braces are safe.

### `.jinja` extension

Files with a `.jinja` extension are rendered and the extension is stripped from
the output name. This is useful when you need syntax highlighting in your editor
for the template source:

```
templates/repolish/pyproject.toml.jinja  →  pyproject.toml
```

## Conditional files

Files whose names start with `_repolish.` are **conditional** — they are staged
only when explicitly mapped to a destination by `create_file_mappings()`. This
lets you ship multiple alternative versions of a file without resorting to
`{% if %}` in the filename or path:

```
templates/repolish/
├── _repolish.ci.github.yml
└── _repolish.ci.gitlab.yml
```

```python
def create_file_mappings(context):
    src = (
        '_repolish.ci.github.yml'
        if context['use_github']
        else '_repolish.ci.gitlab.yml'
    )
    return {'.github/workflows/ci.yml': src}
```

Unconditional files (no `_repolish.` prefix) are always staged and rendered.
See [File Modes](file-modes.md) for create-only and delete behaviours.

## What never reaches your project

- The `_repolish.` prefix files that were not selected by any mapping
- Marker lines from anchor directives (`## repolish-start[...]`, etc.)
- The `.jinja` extension
- Anything outside `templates/repolish/`

The output in `.repolish/_/render/` is always clean before it is applied.
