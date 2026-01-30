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
