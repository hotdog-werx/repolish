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
into the template. Syntax, the preview workflow, and worked examples (including
preserving `version` and `description` in `pyproject.toml`) are covered in
[Regex](../markers/regex.md).

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

The [Markers](../markers/index.md) tab covers each directive family in depth —
[Regex](../markers/regex.md), [Tag Blocks & Anchors](../markers/tag-blocks.md) —
plus [Phases](../markers/phases.md) and debugging with
[`repolish preview`](../reference/preview.md).
