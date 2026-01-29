# Provider Patterns

This document describes recommended patterns for writing Repolish providers that
are maintainable, user-friendly, and work well with the `context_overrides`
feature.

## Namespaced Context Pattern

Providers should organize their context contributions under a namespaced key to
avoid conflicts and make overrides easier.

### Problem

Without namespacing, providers might contribute flat or deeply nested keys that
are hard to override:

```yaml
# Hard to override deeply nested values
context:
  devkits:
    - name: d1
      ref: v0
    - name: d2
      ref: v1
```

Users wanting to change just the first devkit name must copy the entire
structure:

```yaml
context:
  devkits:
    - name: new-d1 # Only this changed
      ref: v0
    - name: d2
      ref: v1
```

### Solution

Namespace provider contexts under a provider-specific key:

```yaml
context:
  my_provider:
    devkits:
      - name: d1
        ref: v0
      - name: d2
        ref: v1
    some_setting: 42
```

Now users can override specific values surgically:

```yaml
context_overrides:
  'my_provider.devkits.0.name': 'new-d1'
  'my_provider.some_setting': 100
```

Alternatively, for convenience, you can use nested dictionary syntax:

```yaml
context_overrides:
  my_provider:
    some_setting: 100
    'devkits.0':
      name: 'new-d1'
      ref: 'v2'
```

Both syntaxes are equivalent - the nested form is automatically flattened to
dot-notation internally.

## Template Usage

In Jinja templates, use `{% set %}` to create local variables for cleaner code:

```jinja
{# Instead of: {{ cookiecutter.my_provider.devkits.0.name }} #}

{%- set prov = cookiecutter.my_provider -%}
{{ prov.devkits.0.name }}
```

This makes templates more readable and maintainable.

## Provider Inputs

For providers that need user input to generate context, use an `*_args` or
`*_config` key:

```yaml
context:
  my_provider_args:
    api_version: v2
    enable_feature_x: true
```

This input affects context generation but typically doesn't appear in templates.
The provider's `create_context()` can read these values:

```python
def create_context(ctx):
    args = ctx.get('my_provider_args', {})
    api_version = args.get('api_version', 'v1')
    # Generate context based on inputs...
    return {
        'my_provider': {
            'api_url': f'https://api.example.com/{api_version}',
            # ...
        }
    }
```

Users set inputs in the context section (not via overrides, since inputs are
read before overrides are applied):

## Why Namespacing Matters

Without namespacing, complex data structures in the root context can cause
issues with Cookiecutter's option handling. For example:

```yaml
# Problematic - Cookiecutter treats arrays as multiple choice options
context:
  names: ['a', 'b', 'c'] # Becomes CLI prompt options, not an array
```

Cookiecutter's CLI treats arrays as multiple choice options, so
`cookiecutter.names` would prompt the user to choose one value instead of being
the full array. Providers work around this by double-wrapping:

```yaml
# Workaround - ugly and confusing
context:
  names: [['a', 'b', 'c']] # cookiecutter.names[0] gives the array
```

With namespacing, this issue disappears entirely:

```yaml
# Clean solution
context:
  my_provider:
    names: ['a', 'b', 'c'] # Works as expected
```

## Benefits

- **Maintainability**: Clear separation of provider concerns
- **User Experience**: Easy to override specific settings
- **Readability**: Templates can use local variables
- **Flexibility**: Providers can accept inputs without cluttering templates
- **Safety**: Namespaced keys prevent accidental overrides between providers
- **Cookiecutter Compatibility**: Avoids option handling issues with arrays and
  complex data structures

## Example Provider

```python
# my_provider/repolish.py

def create_context(ctx):
    args = ctx.get('my_provider_args', {})
    base_url = args.get('base_url', 'https://api.example.com')

    return {
        'my_provider': {
            'api': {
                'base_url': base_url,
                'endpoints': {
                    'users': f'{base_url}/users',
                    'posts': f'{base_url}/posts',
                }
            },
            'features': args.get('features', ['basic']),
        }
    }
```

```yaml
# Project config
context:
  my_provider_args:
    base_url: https://staging.api.example.com
    features: ['basic', 'advanced']

context_overrides:
  'my_provider.api.endpoints.posts': 'https://custom.api.example.com/posts' # Override generated context
```

This pattern scales well as projects grow and add more providers.
