# Template Files

This guide covers how to structure and write template files for Repolish.

## Template Directory Structure

Provider templates are organized under a `repolish/` directory within each
provider. This directory contains the project layout files that will be
processed and copied to your project:

```
my-provider/
├── repolish.py              # Provider factory (required)
└── repolish/                # Template directory (required)
    ├── README.md
    ├── pyproject.toml
    ├── src/
    │   └── __init__.py
    └── tests/
        └── test_example.py
```

All files under `repolish/` will be processed with Jinja2 templating and copied
to your project when you run `repolish`.

## Jinja Extension for Syntax Highlighting

Template files can optionally use a `.jinja` extension to enable proper syntax
highlighting in editors like VS Code. This is especially useful for
configuration files that contain Jinja template syntax:

```
repolish/
├── pyproject.toml.jinja     # TOML with Jinja highlighting
├── config.yaml.jinja        # YAML with Jinja highlighting
├── Dockerfile.jinja         # Dockerfile with Jinja highlighting
└── README.md                # Regular Markdown (no .jinja needed)
```

### How It Works

When Repolish processes your templates, it automatically strips the `.jinja`
extension from filenames before copying them to your project:

- `pyproject.toml.jinja` → `pyproject.toml`
- `config.yaml.jinja` → `config.yaml`
- `Dockerfile.jinja` → `Dockerfile`

This means you get the benefit of syntax highlighting in your editor while
editing templates, but the generated files have normal extensions.

### Editor Configuration

Many VS Code extensions recognize the `.jinja` extension and provide proper
syntax highlighting. For example:

- **YAML files**: `config.yaml.jinja` gets both YAML and Jinja highlighting
- **TOML files**: `pyproject.toml.jinja` gets TOML and Jinja highlighting
- **HTML files**: `template.html.jinja` gets HTML and Jinja highlighting

Common extensions that support this pattern:

- [Better Jinja](https://marketplace.visualstudio.com/items?itemName=samuelcolvin.jinjahtml)
- [Jinja](https://marketplace.visualstudio.com/items?itemName=wholroyd.jinja)

### Special Case: Actual Jinja Templates

If you need to generate actual `.jinja` files (files that will themselves be
Jinja templates), use a double `.jinja.jinja` extension:

```
repolish/
└── my-template.jinja.jinja  # Generates: my-template.jinja
```

The rule is simple: if a template filename ends in `.jinja`, that extension will
be removed in the generated output.

## Template Syntax

Templates use Jinja2 syntax to reference context variables:

```jinja
# {{ cookiecutter.package_name }}

Version: {{ cookiecutter.version }}
Author: {{ cookiecutter.author }}
```

See the [Preprocessors guide](preprocessors.md) for information about advanced
features like anchors, create-only blocks, and conditional content.

## Jinja rendering (opt-in) and Cookiecutter deprecation

Historically Repolish used Cookiecutter for the final render pass. Newer
projects can opt into native Jinja2 rendering which provides stricter
validation, better error messages, and more flexible features (for example
`tuple`-valued `file_mappings` and per-file extra context).

- Enable native Jinja rendering in your `repolish.yaml`:

```yaml
# Use native Jinja for rendering (opt-in; default: false)
no_cookiecutter: true
```

- What changes when you opt in:
  - Templates are rendered with Jinja2 using the merged provider context.
  - The merged context is available _both_ as top-level variables and under the
    legacy `cookiecutter` namespace to ease migration (e.g.
    `{{ my_provider.name }}` and `{{ cookiecutter.my_provider.name }}` both
    work).
  - File _paths_ and _file contents_ are Jinja-rendered (so use `{{ }}` in
    filenames like `src/{{ module_name }}.py.jinja`).
  - `tuple`-valued `file_mappings` are supported (see below).

- Why migrate away from Cookiecutter
  - Cookiecutter treats some data structures (notably arrays) as CLI options
    which complicates templates and provider context. Jinja does not have that
    limitation.
  - Jinja provides better error reporting (we use StrictUndefined by default)
    which surfaces missing variables during preview/apply rather than failing
    silently or producing incorrect output.
  - The new renderer supports per-mapping extra context and avoids Cookiecutter
    CLI prompts or option-handling quirks.

- Migration tips
  - Enable `no_cookiecutter: true` in a local config and run `poe preview` (or
    `repolish preview`) to validate templates.
  - Replace direct `cookiecutter.*` references where convenient with top-level
    variables (both are supported during migration).
  - If you rely on Cookiecutter-specific behaviors, keep the old path but plan
    to move logic into Jinja templates or provider factories.

## Best Practices

1. **Use `.jinja` for syntax highlighting**: Add `.jinja` to files with
   significant Jinja templating to improve editor experience
2. **Keep it optional**: Files without Jinja syntax don't need the extension
3. **Consistent naming**: Use the same pattern across your templates for clarity
4. **Test both ways**: Verify your templates work with and without the extension
   since the generated output is identical
