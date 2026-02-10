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

## Best Practices

1. **Use `.jinja` for syntax highlighting**: Add `.jinja` to files with
   significant Jinja templating to improve editor experience
2. **Keep it optional**: Files without Jinja syntax don't need the extension
3. **Consistent naming**: Use the same pattern across your templates for clarity
4. **Test both ways**: Verify your templates work with and without the extension
   since the generated output is identical
