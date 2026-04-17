# Preserve Your Edits with Preprocessor Directives

Preprocessor directives are markers you embed directly in your template files.
Repolish reads them before Jinja2 runs, captures values from the current project
file, and injects them back so local state survives every apply. All directive
lines are stripped from the final written file.

For cases where a provider needs to fully control a block of content (rather
than reading it from the project), block anchors offer a simpler alternative.

## Regex directives

The most common directive preserves a single line - a version string, a config
value, an author field - by matching it in your existing file and pulling it
into the template:

```
## repolish-regex[my-version]: __version__ = "(.+?)"
__version__ = "0.0.0"
```

Repolish runs the pattern against the current file. If a match is found, the
captured group replaces the line. If not, the default line is used.

### Example - preserving a version string

Provider template:

```python
## repolish-regex[version]: __version__ = "(.+?)"
__version__ = "0.0.0"
```

Your file already contains `__version__ = "1.4.2"`. After every apply that line
stays `1.4.2`. The default `0.0.0` is only used when the file does not exist
yet.

## Block anchors

For cases where the provider needs to inject computed content into a section -
content that changes based on context, like assembling install extras from a
list - use a block anchor:

```
## repolish-start[my-section]
...default content here...
## repolish-end[my-section]
```

The marker style (`##`) can be any comment prefix that fits the file type - `#`,
`//`, `--`, etc. What matters is the `repolish-start[name]` /
`repolish-end[name]` text. All marker lines are stripped - the final project
file is clean.

### How it works

1. The provider's template ships the anchor with default content between the
   markers.
2. During preprocessing, repolish replaces the block with whatever
   `create_anchors()` returns for that key, or whatever `anchors:` in
   `repolish.yaml` specifies (config-level overrides win).
3. If no replacement is provided, the default content is kept.
4. The marker lines are stripped from the final written file.

To override an anchor from `repolish.yaml`, add an `anchors` mapping under the
relevant provider:

```yaml
providers:
  mylib:
    cli: mylib-link
    anchors:
      install-extras: 'pip install -e ".[dev,docs]"'
```

The value must be the full replacement string (no markers). Config-level anchors
are merged on top of anchor values returned by the provider, so you only need to
specify the keys you want to override.

Anchor overrides are scoped to the provider they are declared under. Setting
`anchors:` on one provider entry cannot affect anchors contributed by a
different provider. This mirrors how `context` overrides work: each provider's
configuration section is isolated.

Because anchor names are defined by the provider's `create_anchors()`
implementation, providers should document which anchor keys they support and
what content each key expects. Without that documentation, project maintainers
have no way to discover which names are valid or what format the replacement
string should follow.

The tradeoff: to customise the injected content you override it in
`repolish.yaml`, because editing the file directly won't stick - the next apply
overwrites it with whatever the provider computes. With regex directives the
file is always the source of truth.

### Example - provider injects custom install extras

Provider template:

```makefile
## repolish-start[install-extras]
pip install -e ".[dev]"
## repolish-end[install-extras]
```

Provider `create_anchors()`:

```python
def create_anchors(self, context: Ctx) -> dict[str, str]:
    extras = ",".join(["dev", *context.extra_groups])
    return {"install-extras": f'pip install -e ".[{extras}]"'}
```

Applied result (marker lines stripped):

```makefile
pip install -e ".[dev,docs,gpu]"
```

## When to use each

Use **regex or multiregex directives** when:

- You want the template to read local values automatically (versions, pinned
  tools, project-specific config).
- The content lives in the file itself - readable and editable without opening
  any config file.
- The project file is the source of truth.

Use **block anchors** when:

- The provider must compute the content at apply time (e.g. assembling install
  extras from a context list) and there is no clean regex equivalent.
- You accept that the actual content will live in `create_anchors()` or
  `repolish.yaml` rather than in the file itself.

Use [`paused_files`](pause.md) when you want to own the _whole file_ and not
just a section of it.

## Further reading

The [Preprocessors guide](../concepts/preprocessors.md) covers multiregex
directives (matching structured blocks like `[tools]` sections), processing
order, and debugging with `repolish preview`.
