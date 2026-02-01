# Preprocessors

Repolish uses preprocessor directives in template files to define how content
should be processed and replaced. These directives allow you to create flexible
templates that can preserve local customizations while maintaining consistency.

## Block Anchors

Block anchors allow you to define sections of content that can be replaced
entirely or preserved with defaults.

### Syntax

```markdown
## repolish-start[anchor-name]

Default content goes here

## repolish-end[anchor-name]
```

### Usage

Block anchors are replaced with content from the context under the same key
name. If no content is provided in the context, the default content between the
markers is preserved.

**Example:**

```yaml
# Template
## repolish-start[header]
# Default Header
Welcome to our project!
## repolish-end[header]

# Context
header: |
  # Custom Header
  Welcome to My Awesome Project!
```

**Result:**

```markdown
# Custom Header

Welcome to My Awesome Project!
```

## Regex Replacements

Regex replacements allow you to preserve specific values from existing files
using regular expressions.

### Syntax

```markdown
## repolish-regex[anchor-name]: pattern

default_value
```

### Usage

The regex pattern captures values from the target file, and the default value is
used when no match is found.

**Example:**

```python
# Template
## repolish-regex[version]: __version__ = "(.+?)"
__version__ = "0.0.0"

# Target file contains: __version__ = "1.2.3"
```

**Result:**

```python
__version__ = "1.2.3"
```

## Multiregex Replacements

Multiregex replacements allow you to process entire configuration sections with
multiple key-value pairs, extracting all values from a block and replacing
template defaults.

### Syntax

```ini
## repolish-multiregex-block[block-name]: block_pattern
## repolish-multiregex[block-name]: item_pattern
key1 = "default1"
key2 = "default2"
key3 = "default3"
```

### Usage

The `multiregex-block` defines the pattern to extract the entire block from the
target file. The `multiregex` pattern defines how to extract individual
key-value pairs within that block.

**Example:**

```ini
# Template
[tools]
## repolish-multiregex-block[tools]: ^\[tools\](.*?)(?=\n\[|\Z)
## repolish-multiregex[tools]: ^(")?([^"=\s]+)(")?\s*=\s*"([^"]+)"$
uv = "0.0.0"
dprint = "0.0.0"
starship = "0.0.0"

# Target file contains:
[tools]
uv = "0.7.20"
dprint = "0.50.1"
starship = "1.0.0"
```

**Result:**

```ini
[tools]
uv = "0.7.20"
dprint = "0.50.1"
starship = "1.0.0"
```

## Processing Order

Preprocessors are applied in the following order:

1. **Block anchors** - Replace entire sections
2. **Regex replacements** - Replace individual values
3. **Multiregex replacements** - Replace multiple values in blocks

## Best Practices

- Use descriptive anchor names that clearly indicate their purpose
- Test your regex patterns thoroughly to ensure they match the expected content
- For complex configurations, consider using multiregex for entire sections
- Keep default values in templates to ensure files work without context
- Use the debugger to validate your preprocessor patterns
