# Resource Linker

The `repolish.linker` module helps libraries link their resources (templates,
configs, docs) to projects. Each library provides its own CLI that users run to
create links, enabling a decentralized resource distribution model.

## Quick Start for Library Authors

Create a simple CLI using the `resource_linker` decorator:

```python
# mylib/cli_link.py
from repolish.linker import resource_linker

@resource_linker(
    library_name='mylib',
    default_source_dir='resources',  # Relative to package root
    templates_subdir='templates',     # Where templates live (default: 'templates')
)
def main():
    """Link mylib resources to your project."""
    print("✓ mylib resources are now available!")

if __name__ == '__main__':
    main()
```

Register in `pyproject.toml`:

```toml
[project.scripts]
mylib-link = "mylib.cli_link:main"
```

That's it! Your library now has a full-featured link CLI.

## What the Decorator Provides

The `resource_linker` decorator automatically creates a CLI with these features:

- **`--source-dir PATH`**: Override source directory
- **`--target-dir PATH`**: Override target (default: `.repolish/library-name`)
- **`--force`**: Force recreation even if target exists
- **`--info`**: Output JSON for repolish orchestration

### Platform Support

Automatically handles platform differences:

- **Unix/macOS**: Creates symlinks (always points to current library version)
- **Windows**: Falls back to copying if symlinks aren't supported
- **Auto-detection**: Tests symlink support at runtime

## For Project Users

### Installing and Linking Resources

1. Install the library:
   ```bash
   uv add mylib
   ```

2. Link resources:
   ```bash
   mylib-link
   ```

3. Resources are now in `.repolish/mylib/`

### Provider Info for Auto-Discovery

When you run `mylib-link`, a `.provider-info.json` file is automatically created
in `.repolish/mylib/`. This file contains metadata about the provider, including
the location of its templates directory.

Repolish uses this information to automatically discover template directories
when you have `providers_order` configured but no explicit `directories` field.
This allows for a simpler, cleaner `repolish.yaml`:

```yaml
# No directories needed!
providers_order:
  - mylib

providers:
  mylib:
    link: mylib-link

context:
  package_name: 'my-project'
```

See the [Configuration guide](../configuration/overview.md) for more details on
auto-discovery.

### Updating Resources

On Unix/macOS with symlinks, updates are automatic. On Windows or to force an
update:

```bash
pip install --upgrade mylib
mylib-link --force
```

## Recommended Package Structure

Organize your library resources clearly:

```
mylib/
├── __init__.py
├── cli_link.py        # Link CLI with @resource_linker
├── core.py            # Library code
└── resources/         # Resources to link
    ├── templates/     # Template files
    │   ├── config.yaml
    │   └── README.md
    ├── configs/       # Config files
    │   ├── .editorconfig
    │   └── .prettierrc
    └── docs/          # Documentation
        └── guide.md
```

## Decorator API Reference

### resource_linker

Creates a CLI decorator for linking library resources.

```python
def resource_linker(
    *,
    library_name: str,
    default_source_dir: str,
    default_target_base: str = '.repolish',
    templates_subdir: str = 'templates',
) -> Callable
```

**Parameters:**

- `library_name` (str): Name of the library (used for default target
  subdirectory)
- `default_source_dir` (str): Path to resources **relative to package root**
  (e.g., `'resources'` or `'mylib/templates'`)
- `default_target_base` (str): Default base directory for target (default:
  `'.repolish'`)
- `templates_subdir` (str): Subdirectory within resources containing templates
  (default: `'templates'`)

**Important**: `default_source_dir` is relative to your **package root**, not
the file where the decorator is used. The decorator automatically finds your
package root and resolves the path.

**Example:**

```python
@resource_linker(
    library_name='codeguide',
    default_source_dir='resources',  # Resolves to <package-root>/resources
)
def main():
    pass
```

## Low-Level API

For advanced use cases where you need more control than the decorator provides.

### link_resources

Manually link library resources to a target directory.

```python
from pathlib import Path
from repolish.linker import link_resources

source = Path(__file__).parent / 'resources'
target = Path('.repolish/mylib')

is_symlink = link_resources(
    source_dir=source,
    target_dir=target,
    force=False,
)
```

**Parameters:**

- `source_dir` (Path): Path to the library's resource directory
- `target_dir` (Path): Path where resources should be linked
- `force` (bool): If True, recreate even if target exists

**Returns:** `True` if symlink was created, `False` if copied

**Raises:** `FileNotFoundError`, `ValueError`

### create_additional_link

Create additional symlinks from repo to provider resources (used by repolish
orchestration).

```python
from repolish.linker import create_additional_link

cli_info = {
    'library_name': 'codeguide',
    'source_dir': '/path/to/site-packages/codeguide/resources',
    'target_dir': '/path/to/project/.repolish/codeguide',
}

create_additional_link(
    cli_info=cli_info,
    source='configs/.editorconfig',  # Relative to resources
    target='.editorconfig',           # Relative to repo root
    force=False,
)
```

**Parameters:**

- `cli_info` (dict): Information from CLI's `--info` output
  - `library_name`: Name of the library
  - `source_dir`: Absolute path to library's resources
  - `target_dir`: Absolute path where resources are linked
- `source` (str): Path relative to provider's resources
- `target` (str): Path relative to repository root
- `force` (bool): If True, remove existing target before linking

**Returns:** `True` if symlink was created, `False` if copied

**Raises:** `FileNotFoundError`, `FileExistsError`

## Best Practices

### For Library Authors

1. **Clear naming**: Use `[library-name]-link` pattern (e.g., `mylib-link`)
2. **Sensible defaults**: Target `.repolish/library-name` by default
3. **Use the decorator**: It handles all CLI boilerplate and `--info` support
4. **Document clearly**: Explain how to link resources in your README

**Example README section:**

````markdown
## Installing Resources

After installing the package:

```bash
mylib-link
```

This creates a symlink (or copy on Windows) at `.repolish/mylib/`.
````

### For Project Users

1. **Add to .gitignore**: The `.repolish/` directory contains symlinks/copies
   that shouldn't be committed
2. **Update with --force**: After library updates on Windows, run
   `mylib-link --force`
3. **Document dependencies**: List required link commands in your project
   documentation

## Examples

### Complete Library Setup

**Directory structure:**

```
mylib/
├── __init__.py
├── cli_link.py
└── resources/
    ├── templates/
    │   └── config.yaml
    └── configs/
        └── .editorconfig
```

**cli_link.py:**

```python
from repolish.linker import resource_linker

@resource_linker(
    library_name='mylib',
    default_source_dir='resources',
)
def main():
    print("✓ mylib resources linked!")

if __name__ == '__main__':
    main()
```

**pyproject.toml:**

```toml
[project]
name = "mylib"
dependencies = ["repolish"]

[project.scripts]
mylib-link = "mylib.cli_link:main"
```

### Custom Templates Subdirectory

If your templates are in a non-standard location:

```python
@resource_linker(
    library_name='mylib',
    default_source_dir='resources',
    templates_subdir='custom_templates',  # Instead of 'templates'
)
def main():
    pass
```

### Multiple Resource Packages

A library can provide multiple link CLIs for different resource sets:

```python
# mylib/cli_link_templates.py
@resource_linker(
    library_name='mylib-templates',
    default_source_dir='templates',
)
def main():
    print("✓ Templates linked!")

# mylib/cli_link_configs.py
@resource_linker(
    library_name='mylib-configs',
    default_source_dir='configs',
)
def main():
    print("✓ Configs linked!")
```

Register both:

```toml
[project.scripts]
mylib-link-templates = "mylib.cli_link_templates:main"
mylib-link-configs = "mylib.cli_link_configs:main"
```
