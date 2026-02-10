# Command Line Interface

Repolish provides several command-line tools for different operations. This
section documents all available CLI commands and their options.

## `repolish`

The primary command for applying templates to projects.

```bash
repolish [OPTIONS]
```

#### Options

- `--config PATH`: Path to repolish configuration file (default:
  `repolish.yaml`)
- `--check`: Load config and create context (dry-run check mode)
- `-v, --verbose`: Increase logging verbosity (-v for verbose, -vv for debug)
- `--version`: Show program's version number and exit
- `--help`: Show help message and exit

#### Behavior

- **Default mode**: Applies template changes to the project
- **Check mode**: Validates configuration and shows what would be changed
  without applying

#### Examples

```bash
# Apply template changes (default behavior)
repolish

# Check what changes would be made
repolish --check

# Apply changes with verbose output
repolish -v

# Use a specific config file
repolish --config my-config.yaml
```

## `repolish-debugger`

A specialized tool for testing and debugging preprocessors in isolation.

```bash
repolish-debugger [OPTIONS] debug_file
```

#### Positional Arguments

- `debug_file`: Path to the YAML debug configuration file

#### Options

- `-v, --verbose`: Increase verbosity (-v for verbose, -vv for debug)
- `--show-patterns`: Show extracted patterns from template
- `--show-steps`: Show intermediate processing steps
- `-h, --help`: Show help message and exit

#### Debug File Format

The debug YAML file supports these keys:

- `template` (required): Template content as a string
- `target`: Target file content to extract patterns from
- `config`: Configuration object with anchors

#### Simple Debug File Example

```yaml
template: |
  # My Project
  version = "0.0.0"

target: |
  version = "1.2.3"
```

#### Examples

```bash
# Basic debugging
repolish-debugger debug.yaml

# Show extracted patterns
repolish-debugger debug.yaml --show-patterns

# Full debugging with verbose logs
repolish-debugger debug.yaml --show-patterns --show-steps -vv
```

## Verbose Logging

Both commands support verbose logging levels:

- `-v`: Basic verbose output
- `-vv`: Detailed debug logging (shows internal processing steps)

!!! note "Debug Logging"

    The `-vv` flag enables comprehensive debug messages
    that show exactly what happens during preprocessing. This is particularly useful
    with `repolish-debugger` for understanding complex regex replacements and
    troubleshooting issues.

## `repolish-link`

A command-line tool for orchestrating multiple provider link CLIs. This tool
allows you to run link commands for multiple libraries in a single invocation,
making it easier to manage complex projects that depend on multiple resource
providers.

```bash
repolish-link [OPTIONS]
```

#### Options

- `--config PATH`: Path to repolish configuration file (default:
  `repolish.yaml`)
- `-v, --verbose`: Increase logging verbosity (-v for verbose, -vv for debug)
- `--help`: Show help message and exit

#### Behavior

The tool reads the `providers` section from your `repolish.yaml` configuration
and runs each provider's link CLI in sequence. For each provider:

1. Calls the provider's link CLI (e.g., `codeguide-link`)
2. Creates any additional symlinks specified in the configuration

The order in which providers are processed is determined by the
`providers_order` section in the configuration file. If `providers_order` is not
specified, all providers in the `providers` section are processed in arbitrary
order.

#### Configuration

The `repolish-link` command requires a `providers` section in your
`repolish.yaml` configuration file. Each provider defines the link CLI command
to invoke and optional additional symlinks to create.

```yaml
providers:
  codeguide:
    cli: codeguide-link
    templates_dir: templates
    symlinks:
      - source: configs/.editorconfig
        target: .editorconfig

providers_order:
  - codeguide
```

#### Provider Configuration Options

- `cli` (optional): The CLI command to execute for linking (mutually exclusive
  with `directory`)
- `directory` (optional): Direct path to provider resources (mutually exclusive
  with `cli`)
- `templates_dir` (optional): Subdirectory within provider resources containing
  templates (default: `templates`)
- `symlinks` (optional): Symlinks to create from provider resources to repo
  root. Can be:
  - Omitted: Use the provider's default symlinks (if any)
  - Empty list `[]`: Disable all symlinks
  - Custom list: Override provider defaults

**Note:** Each provider must specify either `cli` or `directory`, but not both.

Each symlink entry has:

- `source`: Path relative to provider resources
- `target`: Path relative to repo root

Many providers define default symlinks (e.g., for `.editorconfig`). You can
override these in your configuration by specifying a custom `symlinks` list or
disable them with `symlinks: []`.

#### Examples

```bash
# Link all configured providers
repolish-link

# Link with verbose output
repolish-link -v

# Use custom config file
repolish-link --config my-config.yaml
```

#### Exit Codes

- `0`: All providers linked successfully
- `1`: Configuration error or one or more providers failed to link

## Exit Codes

- `0`: Success
- `1`: Error occurred
- `2`: Configuration validation failed
- `3`: Template processing failed

## Configuration

The `repolish` command uses the `repolish.yaml` configuration file by default.
See the [Configuration](configuration/) section for details on available
options.

The `repolish-debugger` command uses its own YAML debug file format (described
above) and does not read `repolish.yaml`.
