# Configuration

This section is the reference for every `repolish.yaml` key and for the Python
provider API. Use it when you know what you are looking for. If you want a
conceptual introduction to how things fit together, start with
[How It Works](../how-it-works/overview.md).

## Pages in this section

### [repolish.yaml schema](config-file.md)

The full list of top-level keys accepted by `repolish.yaml` - `providers`,
`providers_order`, `template_overrides`, `context`, `context_overrides`,
`anchors`, `delete_files`, `post_process`, and `paused_files`. Covers the
Pydantic model behind the file and notes on schema evolution.

### [Provider settings](providers.md)

How each provider entry is resolved: the `cli`, `provider_root`, and
`resources_dir` fields; the resolution priority rules; how `repolish link`
registers providers; and the CLI protocol a link command must follow.

### [Provider Python API](context.md)

The Python-side authoring reference: writing `create_context()` with a typed
Pydantic model, using `BaseContext`, class-based `Provider` subclasses, per-file
`TemplateMapping` extra context, cross-provider inputs via `provide_inputs()` /
`finalize_context()`, and how to test provider context.
