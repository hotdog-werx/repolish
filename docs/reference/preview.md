# repolish preview

Preview the full render pipeline for a single template. This is the interactive
debugger for working out template and marker syntax before running a full
`repolish apply` — one YAML file exercises pre-render directives, the Jinja
render, after-render directives, and insertion fills, with the Result matching
what a real apply would write. See the [Markers](../markers/index.md) tab for
the marker families themselves.

```
repolish preview [OPTIONS] DEBUG_FILE
```

## Arguments

The table below is generated from the preview parameter model in the CLI code,
so it cannot drift.

<!-- repolish:on:options cli-options preview -->

| Argument          | Default | Description                               |
| ----------------- | ------- | ----------------------------------------- |
| `DEBUG_FILE`      | `-`     | Path to the YAML debug configuration file |
| `--show-patterns` | `False` | Show extracted patterns from template     |
| `--show-steps`    | `False` | Show intermediate processing steps        |

<!-- repolish:off:options -->

## Debug file format

The debug file is a YAML document with three keys:

```yaml
template: |
  # required - the template content, exactly as it lives in the provider

target: |
  # optional - simulates the current file on disk
  # keep blocks, regex captures, and marker edits are adopted from it

config:
  anchors:
    myblock: |
      # optional - anchor values injected into tag blocks
  context:
    # optional - variables for the Jinja render stage
    python_version: '3.12'
  insertions:
    # optional - entry points resolving to renderer functions
    functions:
      display-year: .prototype:display_year
      env-name: .prototype:env_name
```

### `template` (required)

The template content, exactly as the provider ships it — Jinja syntax included.

### `target` (optional)

The content of the file that already exists on disk. repolish reconciles the
template against it the way a real apply does: regex captures and keep blocks
are preserved from it, and marker edits (function and args on a `repolish:on`
line, zone opening markers) are adopted from it.

### `config` (optional)

- `anchors` — a mapping of anchor names to their replacement values.
- `context` — the Jinja variables the render stage sees. A template variable
  with no entry fails exactly like a real apply (strict undefined), so
  previewing is also a quick way to check which names a template needs.
- `insertions.functions` — a mapping of function name to entry point, in the
  pyproject script form `module:object.attr`. The module is imported and the
  dotted attribute path is walked to the callable, which meets the same calling
  contract a real apply's registered renderers do. Write the functions the way
  provider insertion functions are written — typed parameters filled from the
  marker's args, like `def show_env(env: str) -> str`, or a keyword-only
  `block: InsertionBlock` (importable from `repolish.insertions`) — so a
  finished prototype lifts into `create_file_insertions` unchanged. A leading
  `.` — as in `.prototype:display_year` — imports the module from the scratch
  file's directory, so a prototype module beside the scratch file can hold the
  real functions while you figure out how they should work. The same registry
  fills `repolish:insert` zones: a zone's function is the directive's
  `function="..."` value, or the zone name when omitted. An unresolvable entry
  point fails the preview with a clean error (exit code 1).

## Pipeline

Preview runs every stage an apply would run for the file:

1. **Pre-render directives** — tag blocks (with `anchors`), `regex`,
   `multiregex`, `keep-*`, and pre-render `keep-block`/`insert` directives.
2. **Jinja render** — the pre-render output rendered with `config.context`.
   Strict undefined and syntax errors fail the preview (exit code 1).
3. **After-render directives** — anything tagged `|after-render`, with the
   `target` file's insertion markers spliced back in (adoption).
4. **Insertions** — `repolish:on` blocks and `repolish:insert` zones filled from
   `config.insertions.functions`. A block whose function is missing or raises
   survives with its markers and reports a diagnostic; the exit code stays 0 (a
   real apply continues past failed blocks the same way).

The Result section prints the final text — what would be written on apply. With
`--show-steps`, each intermediate stage prints too, so you can see exactly where
a directive or template error enters the picture.

## Examples

### Basic render

```yaml
template: |
  python_version = "{{ python_version }}"

config:
  context:
    python_version: '3.11'
```

```bash
repolish preview debug.yaml
# -> python_version = "3.11"
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

### After-render keep blocks in a Jinja loop

```yaml
template: |
  ## repolish:keep-block[paths|after-render] start="# additional-paths" end-regex="^provider[0-9]+:$"
  {% for idx in providers %}
  provider{{ idx }}:
     - static{{ idx }}
     # additional-paths
     - default{{ idx }}
  {% endfor %}

target: |
  provider1:
     - static1
     # additional-paths
     - custom1
  provider2:
     - static2
     # additional-paths
     - custom2

config:
  context:
    providers: [1, 2]
```

Each rendered block pairs first-to-first with the target's blocks, so both
custom entries survive the loop. See [keep blocks](../markers/keep-block.md).

### Insertion blocks and zones

```yaml
template: |
  # repolish:on:env show-env staging
  # repolish:off:env

  ## repolish:insert[badges] start="<!-- generated:badges:on" end="<!-- generated:badges:off -->"
  <!-- generated:badges:on my-org/my-repo -->
  _Default badge row._
  <!-- generated:badges:off -->

config:
  insertions:
    functions:
      show-env: .prototype:show_env
      badges: .prototype:badges
```

With a `prototype.py` beside `debug.yaml` holding the real functions, written
exactly as they will live in the provider:

```python
def show_env(env: str) -> str:
    return f'{env} environment'


def badges(owner_repo: str, style: str = 'flat') -> str:
    return f'![ci](https://ci.example/{owner_repo}/badge.svg?style={style})'
```

```bash
repolish preview debug.yaml
```

Edit the marker's args in `target` to try adoption — the adopted arg drives the
filled body. Iterate on `prototype.py` and rerun to try a function shape; when
the prototype is ready, the functions lift into the provider's
`create_file_insertions` unchanged — no project or registration step needed
along the way.

### Inspecting patterns and stages

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
