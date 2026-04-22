# Template files

Templates are files under a provider's `repolish/` directory. On every
`repolish apply` they are rendered with Jinja2 and written to your project.

See [Templates](../concepts/templates.md) for the full reference on directory
layout, Jinja2 rendering, the `repolish.*` namespace, and the `.jinja`
extension.

## Choosing a feature

| Goal                                            | Feature                                             |
| ----------------------------------------------- | --------------------------------------------------- |
| Render the same file on every apply             | Auto-staging (default)                              |
| Pick between alternative files based on context | `create_file_mappings()` with `_repolish.*` sources |
| Group a multi-file variant under one name       | `_repolish.`-prefixed folder                        |
| Write a file once, let the developer own it     | `FileMode.CREATE_ONLY`                              |
| Remove a file from the project                  | `FileMode.DELETE`                                   |
| Preserve a section the developer edits          | [Anchors](preprocessors.md)                         |

## Selecting a file variant

Use `create_file_mappings()` to pick between alternative templates without
`{% if %}` logic in filenames.

Template directory:

```
repolish/
├── pyproject.toml                    # auto-staged when no mapping overrides it
├── _repolish.pyproject.poetry.toml   # selected when use_poetry is True
└── _repolish.pyproject.setup.toml    # selected otherwise
```

Provider code:

```python
from repolish import BaseContext, BaseInputs, Provider, TemplateMapping

class Ctx(BaseContext):
    use_poetry: bool = True

class MyProvider(Provider[Ctx, BaseInputs]):
    def create_file_mappings(
        self, context: Ctx
    ) -> dict[str, str | TemplateMapping | None]:
        return {
            "pyproject.toml": (
                "_repolish.pyproject.poetry.toml" if context.use_poetry
                else "_repolish.pyproject.setup.toml"
            ),
        }
```

`pyproject.toml` also exists under `repolish/` but the mapping wins — it is
rendered from the selected source rather than auto-staged at its own path.

Pass `None` as a value to suppress a file entirely:

```python
"some-file.yml": None,  # don't copy this file at all
```

## Grouping a variant into a folder

When a conditional variant spans multiple files, placing them all under a
`_repolish.`-prefixed directory keeps individual filenames clean. Files inside
the folder mirror the destination structure relative to the target directory:

```
repolish/
├── pyproject.toml
├── _repolish.ci.github/          # entire subtree is staging-only
│   ├── workflows/                # mirrors .github/workflows/
│   │   └── ci.yml
│   └── dependabot.yml
└── _repolish.ci.gitlab/
    └── .gitlab-ci.yml
```

Use `map_folder` to build the mapping dict automatically. It returns a plain
dict you can inspect and adjust before spreading it into the final mapping:

```python
from repolish import BaseContext, BaseInputs, Provider, map_folder

class Ctx(BaseContext):
    use_github: bool = True

class MyProvider(Provider[Ctx, BaseInputs]):
    def create_file_mappings(
        self, context: Ctx
    ) -> dict[str, str | TemplateMapping | None]:
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

Assigning `map_folder(...)` to a variable lets you inspect the generated entries
before returning — handy for debugging. Pass `file_mode` or `extra_context` to
apply the same option to every entry:

```python
github_files = map_folder('.github', '_repolish.ci.github', tpl, file_mode=FileMode.CREATE_ONLY)
```

`repolish lint` warns about any `_repolish.`-prefixed file — including those
inside a prefixed folder — that is never referenced by a mapping.

## Create-only scaffold stubs

Use `FileMode.CREATE_ONLY` to seed files that a developer will own after the
first apply. Subsequent runs skip those files even when the template changes.

```python
from repolish import BaseContext, BaseInputs, FileMode, Provider, TemplateMapping

class Ctx(BaseContext):
    package_name: str = 'mypackage'

class MyProvider(Provider[Ctx, BaseInputs]):
    def create_file_mappings(
        self, context: Ctx
    ) -> dict[str, str | TemplateMapping | None]:
        pkg = context.package_name
        return {
            f'src/{pkg}/__init__.py': TemplateMapping(
                '_repolish.init.py', file_mode=FileMode.CREATE_ONLY,
            ),
            f'src/{pkg}/py.typed': TemplateMapping(
                '_repolish.py.typed', file_mode=FileMode.CREATE_ONLY,
            ),
            'tests/test_main.py': TemplateMapping(
                '_repolish.test_main.py', file_mode=FileMode.CREATE_ONLY,
            ),
        }
```

You can combine `CREATE_ONLY` with conditional selection — use an `if/else` to
pick the source, then wrap it in
`TemplateMapping(..., file_mode=FileMode.CREATE_ONLY)`.

See [File Modes](../concepts/file-modes.md) for the full `TemplateMapping`
reference, `FileMode.DELETE`, and extra-context options.

## Tips

- **Discover templates dynamically**: use `self.templates_root.glob(...)` inside
  a `ModeHandler` to find template files without hard-coding paths.
- **Extra context per file**: pass `extra_context=MyModel(...)` to
  `TemplateMapping` when different destinations need different values from the
  same source template.
- **`repolish lint`** warns about `_repolish.*` files and files inside
  `_repolish.`-prefixed folders that are never referenced by any mapping — a
  useful safety net for typos.
