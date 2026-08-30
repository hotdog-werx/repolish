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
list - use a block anchor (`repolish-start[name]` / `repolish-end[name]`).
Syntax, content sources (`create_anchors()` and the `anchors:` override in
`repolish.yaml`), and a worked example are covered in
[Tag Blocks & Anchors](../markers/tag-blocks.md).

The tradeoff: to customise the injected content you override it in
`repolish.yaml`, because editing the file directly won't stick - the next apply
overwrites it with whatever the provider computes. With regex directives the
file is always the source of truth.

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
