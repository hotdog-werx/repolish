# File Modes

Every file in the merged template set has a mode that controls what repolish
does when it writes (or doesn't write) the destination path. Modes are set
through `TemplateMapping` entries returned by `create_file_mappings()`.

## Modes at a glance

| Mode          | Destination exists | Destination absent     |
| ------------- | ------------------ | ---------------------- |
| `REGULAR`     | Overwrite          | Create                 |
| `CREATE_ONLY` | Skip               | Create once            |
| `DELETE`      | Delete             | Nothing (already gone) |
| `KEEP`        | Cancel a delete    | Nothing                |
| `SUPPRESS`    | Skip (dev use)     | Skip (dev use)         |

## REGULAR (default)

All template files without an explicit mode are regular. On every apply,
repolish overwrites the destination with the rendered output.

```python
# Implicit — no TemplateMapping needed for regular files
# Every file in templates/repolish/ that is not conditional is REGULAR
```

## CREATE_ONLY

A create-only file is written once and never touched again. Ideal for scaffolded
stubs that the developer will own from the start:

```python
from repolish import BaseContext, BaseInputs, FileMode, Provider, TemplateMapping


class MyProvider(Provider[BaseContext, BaseInputs]):
    def create_file_mappings(self, context):
        return {
            'src/mypackage/__init__.py': TemplateMapping(
                'src/mypackage/__init__.py',
                file_mode=FileMode.CREATE_ONLY,
            ),
            'tests/test_main.py': TemplateMapping(
                'tests/test_main.py',
                file_mode=FileMode.CREATE_ONLY,
            ),
        }
```

In `--check` mode, a missing create-only file is reported as `MISSING` but an
existing file with different content is silently ignored (not diffed).

## DELETE

A delete mapping tells repolish to remove a path from the project. No source
template is needed:

```python
def create_file_mappings(self, context):
    return {
        'old-config.ini': TemplateMapping(None, file_mode=FileMode.DELETE),
    }
```

Delete requests are recorded in `.repolish/_/delete-history/` so reviewers can
see why a path was flagged.

If a path appears in both `delete_files` and `create_only_files`, **delete
wins**.

## KEEP

A `KEEP` mapping explicitly cancels a `DELETE` scheduled by an earlier provider.
This is only useful when multiple providers manage the same destination: the
first provider requests deletion, and a later provider overrides the decision.

```python
def create_file_mappings(self, context):
    return {
        'old-config.ini': TemplateMapping(
            'old-config.ini',
            file_mode=FileMode.KEEP,
        ),
    }
```

Both decisions are recorded in `.repolish/_/delete-history/` so reviewers can
see the full provenance chain.

## SUPPRESS

`SUPPRESS` tells repolish to skip staging and rendering for a file entirely.
This is useful during provider development when a template is temporarily broken
and you want the rest of the pipeline to proceed without it:

```python
def create_file_mappings(self, context):
    return {
        'broken-template.toml': TemplateMapping(
            '_repolish.broken.toml',
            file_mode=FileMode.SUPPRESS,
        ),
    }
```

`SUPPRESS` is a programmatic escape hatch for provider authors. Project users
should use
[`template_overrides: null`](../project-controls/template-overrides.md) to
suppress a file from config instead.

## Conditional files and the `_repolish.` prefix

Any path component that starts with `_repolish.` marks that entry as
staging-only — it is never auto-staged and is only reached when a mapping
selects it. This applies to both the file-prefix and the folder-prefix forms.

**File prefix** — for single-file alternatives:

```
templates/repolish/
├── _repolish.ci.github.yml
└── _repolish.ci.gitlab.yml
```

```python
def create_file_mappings(self, context):
    src = (
        '_repolish.ci.github.yml'
        if context.use_github
        else '_repolish.ci.gitlab.yml'
    )
    return {'.github/workflows/ci.yml': src}
```

**Folder prefix** — for multi-file variants where individual filenames should
remain clean. Files inside the folder mirror the destination structure relative
to the target directory:

```
templates/repolish/
├── _repolish.ci.github/
│   ├── workflows/     # mirrors .github/workflows/
│   │   └── ci.yml
│   └── dependabot.yml
└── _repolish.ci.gitlab/
    └── .gitlab-ci.yml
```

Use `map_folder` to build the mapping dict automatically:

```python
from repolish import map_folder

def create_file_mappings(self, context):
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

Or write the entries by hand when you only need a subset of the files:

```python
def create_file_mappings(self, context):
    if context.use_github:
        return {
            '.github/workflows/ci.yml': '_repolish.ci.github/workflows/ci.yml',
            '.github/dependabot.yml':   '_repolish.ci.github/dependabot.yml',
        }
    return {'.gitlab-ci.yml': '_repolish.ci.gitlab/.gitlab-ci.yml'}
```

A conditional file can also carry a mode:

```python
return {
    '.github/workflows/ci.yml': TemplateMapping(
        '_repolish.ci.github.yml',
        file_mode=FileMode.CREATE_ONLY,
    ),
}
```

## Extra context per file

`TemplateMapping` accepts an `extra_context` argument that is merged into the
Jinja2 context for that file only. Useful when different destinations need
different values from the same template:

```python
return {
    'packages/core/pyproject.toml': TemplateMapping(
        '_repolish.pyproject.toml',
        extra_context={'package_name': 'core'},
    ),
    'packages/cli/pyproject.toml': TemplateMapping(
        '_repolish.pyproject.toml',
        extra_context={'package_name': 'cli'},
    ),
}
```
