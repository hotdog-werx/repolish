# Insertions

Insertions let a provider fill reserved blocks inside files that are not fully
owned by template rendering.

Use insertions when a developer-owned file needs one or more generated regions,
while the rest of the file stays hand-edited.

- `create_file_mappings()` owns and writes entire files
- `create_file_validators()` checks final files
- `create_file_insertions()` fills explicit blocks in existing files

## Where insertions fit in apply

Insertions run in the apply pipeline after generated files are written, then
report per-file insertion status in the summary.

In check mode, insertion output is also checked for drift. If insertion-managed
content is stale, `repolish apply --check` fails just like template drift.

## Marker format

A reserved block is defined with an `on/off` pair. The tag is optional and
serves as a visual aid for developers to track matching pairs:

```html
<!-- repolish:on:updated last-updated -->
<!-- repolish:off:updated -->
```

The `on` marker includes:

- tag: `updated` (optional, for visual matching)
- function name: `last-updated`
- optional args after the function name

### Syntax variations

The colon and tag are both optional. All of these are valid:

```html
<!-- With tag (recommended for clarity) -->
<!-- repolish:on:updated last-updated -->
<!-- repolish:off:updated -->

<!-- Empty tag with colon (shorter) -->
<!-- repolish:on: last-updated -->
<!-- repolish:off: -->

<!-- No colon at all (shortest) -->
<!-- repolish:on last-updated -->
<!-- repolish:off -->
```

Example with args:

```html
<!-- repolish:on:env env-info PYTHON_VERSION -->
<!-- repolish:off:env -->
```

When using empty tags, you cannot nest blocks with the same empty tag (just like
any repeated tag name). Multiple sequential empty-tag blocks work fine.

## Registering insertion functions

`create_file_insertions()` is keyed by explicit destination path and function
name.

### Function signature patterns

Insertion functions are called based on their signature. The system uses
**strict typing** - you must declare your parameters explicitly. Do not use
`*args` unless you genuinely need variadic arguments.

**Recommended: keyword-only `context` parameter**

Use `BlockContext` to access insertion metadata and repolish context:

```python
from repolish import BaseContext, BaseInputs, Provider
from repolish.insertions import BlockContext
from datetime import datetime


class Ctx(BaseContext):
    pass


class MyProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_insertions(self, context: Ctx):
        def render_year(*, context: BlockContext) -> str:
            """Access repolish context via BlockContext."""
            return str(context.repolish.year)

        def render_with_args(*, context: BlockContext) -> str:
            """Access marker args via BlockContext."""
            # context.tag -> the tag name from the marker
            # context.args -> tuple of positional args from the marker
            # context.repolish -> full repolish context (workspace, repo, provider)
            if context.args:
                return f"Called with: {', '.join(context.args)}"
            return "No args provided"

        return {
            'README.md': {
                'render-year': render_year,
                'render-with-args': render_with_args,
            },
        }
```

**Positional arguments**

For simple cases, use positional parameters with clear names:

```python
def env_info(env_var: str, default: str = "unknown") -> str:
    """Get environment variable with a default."""
    import os
    return os.environ.get(env_var, default)
```

Marker: `<!-- repolish:on:env env-info PYTHON_VERSION 3.11 -->`

**Variadic arguments (`*args`)**

Only use `*args` when you need truly flexible arity:

```python
def join_items(*args: str) -> str:
    """Join arbitrary number of items."""
    return ", ".join(args)
```

Marker: `<!-- repolish:on:items join-items apple banana cherry -->`

**Zero-argument functions**

For static content:

```python
def static_header() -> str:
    """Return a fixed header."""
    return "## Generated Section\n"
```

### Key points about strong typing

- **Always annotate parameter types** - the system inspects your signature
- **Use `BlockContext` for context access** - annotate with
  `*, context: BlockContext`
- **Avoid `*args` unless necessary** - prefer explicit positional parameters
- **Use default values for optional params** - `default: str = "unknown"`
- **Return type should be `str`** - the rendered content

The signature inspection follows this order:

1. Single `InsertionBlock` param → passes full block (internal wrapper pattern)
2. `*args` → passes all marker args positionally
3. Positional params → filled from marker args, uses defaults if available
4. Keyword-only `context: BlockContext` → auto-injected with full context

## Dynamic explicit file mapping (recommended)

Insertion registry keys are explicit file paths, not glob patterns.

If you want broad coverage like all files under `docs/`, do the discovery in
provider code and build an explicit mapping dynamically. This keeps ownership
clear and makes the final insertion target set fully visible in provider output.

```python
from pathlib import Path

from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    pass


class DocsProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_insertions(self, context: Ctx):
        def render_last_updated(*, context, args):
            return context.repolish.provider.version

        root = context.repolish.workspace.root_dir
        docs_dir = Path(root) / 'docs'
        mappings = {}

        for file_path in docs_dir.rglob('*.md'):
            rel = file_path.relative_to(root).as_posix()
            mappings[rel] = {
                'render-last-updated': render_last_updated,
            }

        return mappings
```

This pattern is the intended way to support directory-wide insertion targets.

## Provider-qualified function names

If multiple providers expose the same function name, use a provider-qualified
name in the marker:

```html
<!-- repolish:on:year alpha:display-year -->
<!-- repolish:off:year -->
```

If an unqualified name is used, repolish resolves it deterministically from the
active provider order.

## Failure behavior and summary output

If a block references an unknown function, insertion does not crash the entire
apply. The block is recorded as failed, diagnostics are written, and summary
output shows mixed status.

Example summary lines:

```text
insertions: ✓ ok (1 ok, 0 failed)
insertions: ✗ failed (1 ok, 1 failed)
```

This makes partial success explicit for files with multiple insertion blocks.

## Real-world examples

### Auto-generating Pydantic model documentation

A common use case is keeping API documentation in sync with code. Instead of
manually updating docs when model fields change, a provider can read the model
and generate the documentation automatically:

```python
from repolish import BaseContext, BaseInputs, Provider
from pydantic import BaseModel
import importlib


class Ctx(BaseContext):
    pass


class PydanticDocsProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_insertions(self, context: Ctx):
        def describe_model(model_path: str) -> str:
            """Load a Pydantic model and return formatted field documentation.
            
            Usage: describe_model('myapp.models:UserCreate')
            """
            module_path, class_name = model_path.rsplit(':', 1)
            module = importlib.import_module(module_path)
            model_class = getattr(module, class_name)
            
            lines = [f'### {class_name}', '']
            for field_name, field_info in model_class.model_fields.items():
                field_type = getattr(field_info.annotation, '__name__', str(field_info.annotation))
                description = field_info.description or 'No description'
                lines.append(f'- **{field_name}** (`{field_type}`): {description}')
            return '\n'.join(lines)

        return {
            'docs/api/models.md': {
                'describe-model': describe_model,
            },
        }
```

Then in your documentation file:

```markdown
# API Models

<!-- repolish:on:models describe-model myapp.models:UserCreate -->
<!-- repolish:off:models -->
```

When you run `repolish apply`, the insertion function loads the actual Pydantic
class and generates up-to-date field documentation automatically. No more
forgetting to update docs when you add a field.

### Listing GitHub organization repositories

Fetch external data and embed it directly in your docs:

```python
import httpx
from repolish import BaseContext, BaseInputs, Provider


class Ctx(BaseContext):
    pass


class GitHubProvider(Provider[Ctx, BaseInputs]):
    def create_context(self) -> Ctx:
        return Ctx()

    def create_file_insertions(self, context: Ctx):
        def list_repos() -> str:
            """Fetch and list all public repos from a GitHub organization."""
            response = httpx.get('https://api.github.com/orgs/myorg/repos')
            response.raise_for_status()
            repos = response.json()
            
            lines = ['| Repository | Description | Stars |', '|-------------|-------------|-------|']
            for repo in sorted(repos, key=lambda r: r['stargazers_count'], reverse=True):
                name = repo['name']
                desc = repo['description'] or 'No description'
                stars = repo['stargazers_count']
                url = repo['html_url']
                lines.append(f'| [{name}]({url}) | {desc} | {stars} |')
            return '\n'.join(lines)

        return {
            'docs/resources/repos.md': {
                'list-repos': list_repos,
            },
        }
```

Usage in markdown:

```markdown
# Our Open Source Projects

<!-- repolish:on:repos list-repos -->
<!-- repolish:off:repos -->
```

This keeps your documentation automatically updated with the latest repository
information. Run `repolish apply` in CI to keep it fresh.

## Insertion reports

For each file with insertion blocks, repolish writes a report artifact:

```text
.repolish/_/insertions/insertions.<path-slug>.json
```

Report fields include:

- `file`
- `source_provider`
- `total_blocks`
- `failed_blocks`
- `functions`
- `diagnostics`

These files are the detailed record behind the compact summary tree output.

## Check mode

Insertions participate in `apply --check`.

- In-sync insertion content: exit code `0`
- Drifted insertion content: exit code `2` with unified diff output

This keeps insertion-managed regions compatible with CI drift checks.

## Monorepo notes

Insertion functions receive provider context, so they can observe workspace mode
(`root`, `member`, `standalone`) and render mode-aware content when needed.

Provider-qualified function names also help avoid collisions in monorepos where
multiple providers may target the same destination file.

## Related pages

- [Templates](templates.md)
- [Validators](validators.md)
- [Monorepo](monorepo.md)
- [Testing Providers](testing.md)
