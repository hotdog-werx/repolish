# Preprocessors

Before Jinja2 runs, repolish applies a preprocessing pass to every staged
template. This pass handles three kinds of directives - all of which are
stripped from the final output so your project files stay clean.

The most common directives are **regex** and **multiregex**: they live inside
the template file itself and read values directly from your current project
file. This makes templates self-contained - no separate config or provider code
is needed to preserve local state. Block anchors are a simpler alternative for
cases where the provider (not the project file) decides what a section contains.

## Regex directives

A regex directive captures a value from your **existing project file** and
injects it back into the template. This is how individual lines survive provider
updates - versions you have already bumped, author fields, local config entries.

```python
## repolish-regex[version]: ^__version__\s*=\s*"(.+?)"$
__version__ = "0.0.0"
```

Repolish runs the pattern against your current file. If a match is found, the
captured group replaces the corresponding line in the template. If no match is
found, the default template line is used unchanged.

The directive line itself is always removed from the output.

## Multiregex directives

For structured blocks (a `[tools]` section in a TOML file, a `requirements`
list, etc.) multiregex directives let you merge additions from the provider
while keeping versions you have already pinned locally.

```toml
[tools]
## repolish-multiregex-block[tools]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
uv = "0.0.0"
dprint = "0.0.0"
```

The block pattern locates the relevant section; the line pattern extracts
key-value pairs. Your existing versions are preserved for matching keys; new
provider keys are appended. See the
[Preprocessors guide](../guides/preprocessors.md) for the full multiregex spec.

## Block anchors

A block anchor marks a section in the template whose content is supplied by the
provider's `create_anchors()` method (which can generate content dynamically
from context, such as assembling install extras from a list) or by an `anchors:`
mapping in `repolish.yaml` (project-level overrides win). All marker lines are
stripped - the final project file is clean.

The tradeoff compared to regex directives: to customise the injected content you
set it in `repolish.yaml`, because editing the file directly won't stick - the
next apply overwrites it with whatever the provider computes.

```makefile
.PHONY: install
install:
## repolish-start[install-extras]
	pip install -e ".[dev]"
## repolish-end[install-extras]
```

The provider supplies the replacement:

```python
def create_anchors(self, context: Ctx) -> dict[str, str]:
    extras = ','.join(['dev', *context.extra_groups])
    return {'install-extras': f'\tpip install -e ".[{extras}]"'}
```

After preprocessing, the marker lines are gone and the injected content is in
place - exactly what Jinja2 will render.

The marker comment style is flexible. Any prefix before `repolish-start[name]`
is accepted, so you can use the comment syntax that fits the file type:

```python
# repolish-start[block]   ← Python / TOML / YAML
// repolish-start[block]  ← JavaScript / CSS
<!-- repolish-start[block] -->   ← HTML / Markdown
/* repolish-start[block] */      ← CSS / C
```

If no replacement is provided for a key, the default content between the markers
is kept (the markers themselves are still stripped).

## Processing order

1. Block anchors are applied first (replacement from provider code / config).
2. Regex directives are applied next (capture from the current project file).
3. Multiregex directives are applied last.

All directive lines are stripped before Jinja2 sees the file.

## Trying it out

Use `repolish preview` with a YAML debug file to experiment without touching
your project. Create a file called `anchor_example.yaml`:

```yaml
template: |
  __version__ = "0.0.0"
  ## repolish-regex[version]: ^__version__\s*=\s*"(.+?)"$

target: |
  __version__ = "1.3.7"
```

Then run:

```bash
repolish preview anchor_example.yaml
```
