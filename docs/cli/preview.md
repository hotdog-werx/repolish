# repolish preview

Preview preprocessor output for a single template. This is the interactive
debugger for working out template and preprocessor syntax before running a full
`repolish apply`.

```
repolish preview [OPTIONS] DEBUG_FILE
```

## Arguments

| Argument     | Description                                                             |
| ------------ | ----------------------------------------------------------------------- |
| `DEBUG_FILE` | Path to a YAML file describing the template and optional target/config. |

## Options

| Option            | Default | Description                                                                     |
| ----------------- | ------- | ------------------------------------------------------------------------------- |
| `--show-patterns` | off     | Print the patterns extracted from the template (anchor tags and regex markers). |
| `--show-steps`    | off     | Print intermediate processing steps.                                            |

## Debug file format

The debug file is a YAML document with three keys:

```yaml
template: |
  # required - the template content

target: |
  # optional - simulates the current file on disk
  # patterns in the target are extracted and merged into the output

config:
  anchors:
    myblock: |
      # optional - anchor values injected into tag blocks
```

### `template` (required)

The Jinja2 template content. Preprocessor directives (anchor tags, regex
markers) are processed first, then the result is treated as output.

### `target` (optional)

The content of the file that already exists on disk. repolish extracts regex
captures from the target and uses them to fill in the template's regex markers.
Omit when the template produces fully static output.

### `config` (optional)

Configuration for the preprocessor. Currently supports:

- `anchors` - a mapping of anchor names to their replacement values.

## Examples

### Basic render

```yaml
template: |
  python_version = "3.11"
```

```bash
repolish preview debug.yaml
```

### Regex capture from target

```yaml
template: |
  version = "0.0.0"
  ## repolish-regex[version]: version = "(.+)"

target: |
  version = "1.2.3"
```

```bash
repolish preview debug.yaml
# -> version = "1.2.3"
```

### Anchor tag replacement

```yaml
template: |
  ## repolish-start[header] ##
  Default header
  ## repolish-end[header] ##

config:
  anchors:
    header: |
      Custom header
      with two lines
```

```bash
repolish preview debug.yaml
```

### Inspecting patterns and steps

```bash
repolish preview debug.yaml --show-patterns --show-steps -vv
```

With `-vv` the output includes structured debug events showing exactly which
tags and regexes were processed and what values were matched:

```
DEBUG starting_text_replacement
  has_anchors: true

DEBUG replacing_tags
  tags: [header]

DEBUG applying_regex_replacements
  regexes: [version]

DEBUG regex_matched_in_target
  matched: 1.2.3
  regex: version
```
