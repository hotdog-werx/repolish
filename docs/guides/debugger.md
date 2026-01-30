# Debugging Preprocessors

Repolish includes a debugger tool for testing and understanding how
preprocessors work with your templates. The `repolish-debugger` command allows
you to experiment with template syntax and see the results instantly.

## Basic Usage

Create a YAML file with your template and optional target/config, then run the
debugger:

```bash
repolish-debugger debug.yaml
```

## Debug File Format

The debug YAML file supports three optional keys:

- `template` (required): The template content as a string
- `target`: The target file content (simulates the file being overwritten)
- `config`: Configuration object with anchors

### Example

```yaml
template: |
  # My Template
  ## repolish-start[header] ##
  Default header content
  ## repolish-end[header] ##

  version = "0.0.0"
  ## repolish-regex[version]: version = "(.+)"

target: |
  version = "1.2.3"

config:
  anchors:
    header: |
      Custom header
      with multiple lines
```

## Command Options

- `--show-patterns`: Display the patterns extracted from the template
- `--show-steps`: Show intermediate processing steps (for future expansion)
- `-v/--verbose`: Increase logging verbosity

## Understanding Preprocessors

### Tag Blocks

Tag blocks allow replacing sections of text with anchor values:

```yaml
template: |
  ## repolish-start[myblock] ##
  This is the default content
  ## repolish-end[myblock] ##

config:
  anchors:
    myblock: 'This replaces the default content'
```

### Regex Replacements

Regex patterns match content in both the template and target file:

```yaml
template: |
  version = "0.0.0"
  ## repolish-regex[version]: version = "(.+)"

target: |
  version = "1.2.3"
```

The regex `version = "(.+)"` finds the version line in both files and replaces
the template's version with the target's captured group.

## Use Cases

- **Template Development**: Test regex patterns and anchor replacements
- **Debugging**: Understand why a preprocessor isn't working as expected
- **Learning**: Experiment with repolish syntax in isolation
- **Documentation**: Create examples of preprocessor usage

## Tips

- Use `|` in YAML for multi-line strings to preserve formatting
- Regex declarations should be on their own line or at line start
- Test complex regexes incrementally with the `--show-patterns` option
- The target file simulates the existing file in your repository
