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
- `-vv`: Enable detailed debug logging showing internal processing steps

## Verbose Debugging

Using `-vv` enables comprehensive debug logging that shows exactly what happens
during preprocessing. This is invaluable for understanding complex regex
replacements and troubleshooting issues.

```bash
repolish-debugger debug.yaml --show-patterns --show-steps -vv
```

### Debug Output Example

With `-vv`, you'll see detailed logs like:

```
DEBUG starting_text_replacement
  has_anchors: true

DEBUG replacing_tags
  tags:
  - header

DEBUG applying_regex_replacements
  regexes:
  - version

DEBUG regex_matched_in_target
  matched: 1.2.3
  regex: version

DEBUG text_replacement_completed
  regexes_applied: 1
  tag_blocks_replaced: 1
```

This shows:

- Whether anchors were provided
- Which tags are being replaced
- Regex matching progress and results
- Final processing summary

!!! note "Debug Logging in Regular CLI"

    The `-vv` flag also works with the main `repolish` command, but it produces
    much more output since it processes all files. The debugger tool is
    recommended for focused debugging of specific templates.

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
- **Debugging**: Understand why a preprocessor isn't working as expected with
  detailed `-vv` logs
- **Learning**: Experiment with repolish syntax in isolation
- **Documentation**: Create examples of preprocessor usage

## Tips

- Use `|` in YAML for multi-line strings to preserve formatting
- Regex declarations should be on their own line or at line start
- Test complex regexes incrementally with the `--show-patterns` option
- Use `-vv` for detailed debugging when patterns aren't working as expected
- The target file simulates the existing file in your repository
