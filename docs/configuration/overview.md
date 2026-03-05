# Configuration

Repolish uses a YAML configuration file (`repolish.yaml` by default) to control
how templates are applied to your project. This file defines which providers
should be used, context variables, anchors, and provider linking.

## Basic Structure

```yaml
# Providers define where to find templates and how to link them to your
# project. Each provider may specify a `cli` command or a direct
# `directory` containing its resources.
providers:
  mylib:
    cli: mylib-link
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
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
  - poe format-dprint
  - poe format-python
```

## Provider Configuration

All template sources are described via the `providers` section. Each provider
entry specifies either:

- a `cli` command to invoke (for external libraries), or
- a `directory` path pointing directly at the provider’s resources.

Optionally you can override or disable the provider’s default symlinks.

```yaml
providers:
  codeguide:
    cli: codeguide-link
  mylib:
    directory: ./local/mylib/resources
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
```

Provider ordering can be controlled with `providers_order`, which is useful when
multiple providers supply the same files (see the
[linker docs](/docs/guides/linker.md)).

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
generation but before the `--check` diff or apply step. This ensures that checks
operate on formatted output.

Commands are executed **once**, in order, with the working directory set to the
rendered project folder inside `.repolish/setup-output/`.

If any command exits with a non-zero status, Repolish fails immediately and
returns a non-zero exit code.

### Command forms

You can provide entries as either a string or an argv list:

```yaml
post_process:
  # String — tokenized with shlex.split and executed without a shell
  - 'ruff --fix .'
  # Argv list — recommended when you need precise control over quoting
  - ['prettier', '--write', 'src/']
  # One-liner python scripts also work as strings
  - "python -c \"open('generated.py','w').write('# auto')\""
```

**Platform note**: On Windows, `shlex` tokenization rules differ from POSIX
shells. If commands include spaces or special characters, prefer the argv-list
form to avoid surprises.

**Security note**: Commands are intentionally executed without `shell=True` to
reduce shell injection risk. If you need shell pipelines or metacharacters, wrap
the logic in a committed script and call it via the argv-list form.

### Example with formatters

```yaml
providers:
  mylib:
    directory: ./templates/my-template
    context:
      package_name: my-project

post_process:
  - poe format
  - ['prettier', '--write', '.']

delete_files: []
```

## Provider Linking Configuration

For projects that use libraries with resource linking capabilities, you can
configure provider linking through the `providers` section. This allows the
`repolish-link` CLI to orchestrate linking across multiple libraries.

```yaml
providers:
  mylib:
    cli: mylib-link
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
  anotherlib:
    cli: anotherlib-link
  locallib:
    directory: ./path/to/locallib/resources
```

### Provider Configuration Options

Each provider in the linking configuration supports these options:

- `cli` (optional): The CLI command to call for linking resources (mutually
  exclusive with `directory`)
- `directory` (optional): Direct path to provider resources (mutually exclusive
  with `cli`)
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
providers_order:
  - codeguide
  - mylib

providers:
  codeguide:
    cli: codeguide-link
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig
      - source: configs/.gitignore
        target: .gitignore

  mylib:
    directory: ./local/mylib/resources
    # default symlinks will be used

post_process:
  - poe format-dprint
```

This example illustrates an explicit provider order with a mix of a linked
package and a local directory. no `directories` field is needed at all.

```yaml
# Another variation: simple single-provider setup
providers:
  codeguide:
    cli: codeguide-link
```

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

- `providers` section missing or empty
- `providers_order` references a provider that is not defined
- Malformed YAML syntax
- Invalid provider configurations (missing CLI/directory, bad symlink entries,
  etc.)

Use `repolish --check` to validate your configuration without applying changes.

**Note:** provider-based directory discovery requires that the link step has run
at least once. `repolish-link` creates `.provider-info.json` files which allow
Repolish to locate the template directories for each provider.
