# Configuration

Repolish uses a YAML configuration file (`repolish.yaml` by default) to control
how templates are applied to your project. This file defines template
directories, context variables, anchors, and provider linking.

## Basic Structure

```yaml
# Template directories to load (optional when using providers)
directories:
  - ./templates
  - ../shared-templates

# Context variables for template rendering (optional)
context:
  package_name: 'my-project'
  version: '1.0.0'
  author: 'Your Name'

# Global anchors for text replacement (optional)
anchors:
  install-deps: |
    pip install requests
    pip install pyyaml

# Files to delete after generation (optional)
delete_files:
  - 'old_file.txt'
  - 'deprecated/'

# Shell commands to run after generation (optional)
post_process:
  - poe format
  - black .

# Provider linking configuration (optional)
providers:
  mylib:
    cli: mylib-link
    templates_dir: templates
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
```

## Directories Section

> **⚠️ DEPRECATED:** The `directories` field is deprecated and will be removed
> in v1.0. Use the `providers` configuration with either `cli` or `directory`
> instead. See the
> [Provider Linking Configuration](#provider-linking-configuration) section
> below.

The `directories` section specifies template directories to load. Each directory
must contain either a `repolish.py` file or a `repolish/` folder with provider
logic.

**Note:** When using provider linking with `providers_order`, the `directories`
field becomes **optional**. If omitted, directories will be automatically built
from the linked providers' template locations. This simplifies configuration
when all your templates come from linked providers.

```yaml
directories:
  - ./templates
  - ../shared-templates
  - /absolute/path/to/templates
```

Paths are resolved relative to the directory containing the `repolish.yaml`
file.

### Auto-Building from Providers

When you use `repolish-link` to link provider resources and have
`providers_order` configured, you can omit the `directories` field entirely:

```yaml
# Simplified configuration - no directories needed!
providers_order:
  - codeguide
  - mylib

providers:
  codeguide:
    cli: codeguide-link
  mylib:
    cli: mylib-link

context:
  package_name: 'my-project'
```

After running `repolish-link`, the directories will be automatically determined
from the `.repolish/<provider>/.provider-info.json` files created during
linking.

## Context Section

The `context` section defines variables that will be available during template
rendering. These can be referenced in templates and by provider factories.

```yaml
context:
  package_name: 'my-project'
  version: '1.0.0'
  python_version: '3.11'
  ci_operating_systems: '["ubuntu-latest", "macos-latest"]'
```

### Context Overrides

Use `context_overrides` to override nested context values using dot-notation:

```yaml
context_overrides:
  some.nested.value: 'overridden'
  another.path: 42
```

## Anchors Section

Anchors define text blocks that can be inserted into templates at specific
locations. They are particularly useful for injecting configuration or code
snippets into generated files.

```yaml
anchors:
  extra-deps: |
    requests = "^5.30"
    pyyaml = "^6.0"
  install: |
    RUN apt-get update && apt-get install -y yq
  version: '1.2.3'
```

See the [Preprocessors guide](../guides/preprocessors.md) for more information
on how anchors are used in templates.

## Delete Files Section

The `delete_files` section specifies files or directories that should be removed
during the apply operation. Use a leading `!` to negate (keep) a
previously-added path.

```yaml
delete_files:
  - 'deprecated_file.txt'
  - 'old_directory/'
  - '*.tmp'
  - '!keep_this.tmp' # Exception to *.tmp
```

## Post Process Section

The `post_process` section defines shell commands to run after template
generation. These are typically formatters or linters.

```yaml
post_process:
  - poe format
  - black .
  - isort .
```

## Provider Linking Configuration

For projects that use libraries with resource linking capabilities, you can
configure provider linking through the `providers` section. This allows the
`repolish-link` CLI to orchestrate linking across multiple libraries.

```yaml
providers:
  mylib:
    cli: mylib-link
    templates_dir: templates
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
  anotherlib:
    cli: anotherlib-link
    templates_dir: ui-templates
  locallib:
    directory: ./path/to/locallib/resources
    templates_dir: templates
```

### Provider Configuration Options

Each provider in the linking configuration supports these options:

- `cli` (optional): The CLI command to call for linking resources (mutually
  exclusive with `directory`)
- `directory` (optional): Direct path to provider resources (mutually exclusive
  with `cli`)
- `templates_dir` (optional): Subdirectory within provider resources containing
  templates (default: `templates`)
- `symlinks` (optional): Symlinks to create from provider resources to repo
  root. Can be:
  - Omitted: Use the provider's default symlinks (if defined in the
    `resource_linker` decorator)
  - Empty list `[]`: Disable all symlinks (override provider defaults)
  - Custom list: Override provider defaults with your own symlinks

**Note:** Each provider must specify either `cli` or `directory`, but not both.

**When to use `cli`:**

- For libraries installed via pip/uv that provide their own link command
- When the provider is a separate package (e.g., `codeguide`, `python-tools`)
- When you want automatic updates via symlinks (on Unix/macOS)

**When to use `directory`:**

- For local provider directories in your repository
- For providers that haven't created their own link CLI yet
- For development/testing of new providers
- When you need direct control over the provider location

### Symlink Configuration

Each symlink entry has:

- `source`: Path relative to provider resources (e.g., `configs/.editorconfig`)
- `target`: Path relative to repo root (e.g., `.editorconfig`)

**Overriding Provider Defaults:**

Many providers define default symlinks (e.g., for `.editorconfig` or
`.gitignore`). You can customize this behavior in your `repolish.yaml`:

```yaml
providers:
  mylib:
    cli: mylib-link
    # Use provider's default symlinks (omit symlinks field)

  anotherlib:
    cli: anotherlib-link
    symlinks: [] # Disable all symlinks

  customlib:
    cli: customlib-link
    symlinks: # Override with custom list
      - source: configs/.editorconfig
        target: .editorconfig
```

### Example: Complete Configuration

```yaml
# Using explicit directories (traditional approach)
directories:
  - ./.pkglink/.codeguide/templates

context:
  codeguide_ref: topic/repolish
  ci_operating_systems: '["windows-latest", "ubuntu-latest", "macos-latest"]'

post_process:
  - poe format-dprint

providers:
  codeguide:
    cli: codeguide-link
    templates_dir: templates
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
      - source: configs/.gitignore
        target: .gitignore
```

### Example: Simplified Configuration with Auto-Discovery

```yaml
# No directories needed - auto-built from providers!
providers_order:
  - codeguide

context:
  codeguide_ref: topic/repolish
  ci_operating_systems: '["windows-latest", "ubuntu-latest", "macos-latest"]'

post_process:
  - poe format-dprint

providers:
  codeguide:
    cli: codeguide-link
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
      - source: configs/.gitignore
        target: .gitignore
```

After running `repolish-link`, the templates directory
(`.repolish/codeguide/templates`) will be automatically discovered and used.

## Providers Order Section

The `providers_order` section specifies the order in which to process providers
during template processing. This affects the order in which context is collected
and merged.

```yaml
providers_order:
  - base_provider
  - specific_provider
  - override_provider
```

See the [Context guide](context.md) for more information on how provider
ordering affects context merging.

## Template Overrides

The `template_overrides` section gives you per‑file control over which provider
supplies a template. Instead of always using the last provider defined in
`providers_order`, you can specify glob patterns that map to a particular
provider alias. When a file path matches a pattern, the matching provider will
be used as the source for that file even if a later provider would normally
override it.

Patterns use standard [fnmatch](https://docs.python.org/3/library/fnmatch.html)
glob syntax and are evaluated in YAML order (later patterns take precedence).
The values must reference providers that are defined elsewhere in the
configuration; an invalid alias will trigger a validation error when the config
is loaded.

```yaml
providers_order:
  - base
  - db
  - api

providers:
  base:
    cli: base-link
  db:
    cli: db-link
  api:
    cli: api-link

template_overrides:
  'README.md': 'base' # keep the README from the base provider
  'src/db/*': 'db' # use the db provider for anything under src/db
  '**/*.py': 'api' # API provider wins for all Python files
```

This feature is particularly useful when you need fine‑grained control over
template resolution without changing the overall provider order.

## Configuration Validation

Repolish validates your configuration file when loading. Common validation
errors include:

- Missing both `directories` and `providers_order` sections (at least one is
  required)
- Invalid directory paths (not a directory or missing `repolish.py`/`repolish/`)
- Malformed YAML syntax
- Invalid provider configurations

Use `repolish --check` to validate your configuration without applying changes.

**Note:** When using provider-based directory discovery, make sure you've run
`repolish-link` at least once to create the `.provider-info.json` files that
repolish uses to find template directories.
