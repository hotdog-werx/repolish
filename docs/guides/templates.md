# Template files

Templates are files under a provider's `repolish/` directory. On every
`repolish apply` they are rendered with Jinja2 and written to your project.

See [Templates](../how-it-works/templates.md) for the full reference on
directory layout, Jinja2 rendering, the `repolish.*` namespace, and the `.jinja`
extension.

## Choosing a feature

| Goal                                            | Feature                                             |
| ----------------------------------------------- | --------------------------------------------------- |
| Render the same file on every apply             | Auto-staging (default)                              |
| Pick between alternative files based on context | `create_file_mappings()` with `_repolish.*` sources |
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

See [File Modes](../how-it-works/file-modes.md) for the full `TemplateMapping`
reference, `FileMode.DELETE`, and extra-context options.

## Tips

- **Discover templates dynamically**: use `self.templates_root.glob(...)` inside
  a `ModeHandler` to find template files without hard-coding paths.
- **Extra context per file**: pass `extra_context=MyModel(...)` to
  `TemplateMapping` when different destinations need different values from the
  same source template.
- **`repolish lint`** warns about `_repolish.*` files never referenced by any
  mapping — a useful safety net for typos.
