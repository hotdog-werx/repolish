# Testing Providers

The `repolish.testing` module gives provider authors a lightweight harness for
exercising provider hooks without a full CLI pipeline, git repo, or installed
wheels. Import it directly in your test suite:

```python
from repolish.testing import ProviderTestBed, assert_snapshots, make_context
```

---

## ProviderTestBed

`ProviderTestBed` is a dataclass that wraps a provider instance, injects a
synthetic context, and exposes methods mirroring every lifecycle hook.

### Quick start

```python
from repolish.testing import ProviderTestBed
from my_provider.repolish.provider import MyProvider

bed = ProviderTestBed(MyProvider)
assert bed.resolved_context.repolish.workspace.mode == 'standalone'
```

When no context is supplied the provider's own `create_context()` is called.
Pass an explicit context to override:

```python
from my_provider.repolish.models import MyProviderContext

bed = ProviderTestBed(
    MyProvider,
    context=MyProviderContext(flag=True),
)
assert bed.resolved_context.flag is True
```

### Constructor parameters

| Parameter        | Type                                     | Default           | Description                                                         |
| ---------------- | ---------------------------------------- | ----------------- | ------------------------------------------------------------------- |
| `provider_class` | `type[Provider]`                         | required          | The concrete `Provider` subclass to test.                           |
| `context`        | context model or `None`                  | `None`            | If `None`, calls `create_context()` on the provider.                |
| `mode`           | `'standalone'` \| `'root'` \| `'member'` | `'standalone'`    | Controls mode-handler dispatch and `repolish.workspace.mode`.       |
| `templates_root` | `Path` or `None`                         | `None`            | Explicit path to `resources/templates`. Auto-detected when omitted. |
| `alias`          | `str`                                    | `'test-provider'` | Provider alias injected into instance metadata.                     |
| `version`        | `str`                                    | `'0.1.0'`         | Provider version injected into instance metadata.                   |

### Lifecycle hook methods

Each method calls the corresponding provider hook through the same dispatch path
that `repolish apply` uses, including mode-handler routing:

```python
bed.file_mappings()         # -> dict[str, str | TemplateMapping | None]
bed.anchors()               # -> dict[str, str]
bed.symlinks()              # -> list[Symlink]
bed.promote_file_mappings() # -> dict[str, str | TemplateMapping | None]
bed.provide_inputs()        # -> Sequence[BaseInputs]
bed.finalize(received_inputs=[])  # -> context
```

`provide_inputs()` and `finalize()` accept optional `all_providers` and
`provider_index` keyword arguments. When omitted they default to a single-entry
list containing the test provider itself.

### Template rendering

#### `render(template_name, *, extra_context=None)`

Renders a single template from `resources/templates/repolish/` using the
provider's context (flattened through `ctx_to_dict`, matching production).

```python
bed = ProviderTestBed(MyProvider)
output = bed.render('mise.toml.jinja')
assert '[tools]' in output
```

#### `render_all(*, extra_context=None)`

Renders every file returned by `create_file_mappings()` plus auto-discovered
templates, returning a `{dest_path: rendered_content}` dict:

```python
rendered = bed.render_all()
assert '.github/workflows/ci.yml' in rendered
assert 'my-project' in rendered['README.md']
```

Auto-discovery mirrors production behavior: files in `templates/repolish/`
without the `_repolish.` prefix are included automatically, while `_repolish.`
prefixed files appear only when explicitly mapped.

---

## make_context

Factory for a synthetic `RepolishContext` with sensible defaults. Useful when
building context objects for tests without constructing the full object graph:

```python
from repolish.testing import make_context

ctx = make_context(mode='root', alias='my-provider', version='2.0.0')
assert ctx.workspace.mode == 'root'
assert ctx.provider.alias == 'my-provider'
```

| Parameter    | Default           | Description                             |
| ------------ | ----------------- | --------------------------------------- |
| `mode`       | `'standalone'`    | `'standalone'`, `'root'`, or `'member'` |
| `alias`      | `'test-provider'` | Provider alias                          |
| `version`    | `'0.1.0'`         | Provider version                        |
| `repo_owner` | `'test-owner'`    | GitHub repo owner                       |
| `repo_name`  | `'test-repo'`     | GitHub repo name                        |

---

## assert_snapshots

Compares rendered output against golden files on disk. Produces a unified diff
on mismatch and reports missing snapshots with the rendered content so you can
copy it into place:

```python
from repolish.testing import ProviderTestBed, assert_snapshots

bed = ProviderTestBed(MyProvider)
rendered = bed.render_all()
assert_snapshots(rendered, 'tests/snapshots/my_provider')
```

### Workflow

1. Run `render_all()` to get the rendered output dict.
2. Create a `tests/snapshots/` directory with expected files matching each key.
3. Call `assert_snapshots(rendered, snapshot_dir)`.
4. On first run (empty snapshot dir), the assertion fails with the rendered
   content printed — copy it into the snapshot directory.
5. On subsequent runs, any drift produces a readable unified diff.

```
AssertionError: 1 snapshot(s) failed:

--- snapshot/README.md
+++ rendered/README.md
@@ -1,3 +1,3 @@
-# old-project
+# new-project
```

---

## Testing mode handlers

`ProviderTestBed` routes calls through the same `call_provider_method` dispatch
that production uses. Set the `mode` parameter to exercise specific handlers:

```python
bed_root = ProviderTestBed(MyProvider, mode='root')
root_mappings = bed_root.file_mappings()

bed_member = ProviderTestBed(MyProvider, mode='member')
member_mappings = bed_member.file_mappings()

assert 'root-only.md' in root_mappings
assert 'member-only.md' in member_mappings
```

---

## Testing cross-provider inputs

Exercise `provide_inputs()` and `finalize()` to verify input exchange without
running the full pipeline:

```python
from my_provider.repolish.models import MyProviderInputs

bed = ProviderTestBed(MyProvider)

# Check what inputs this provider emits
inputs = bed.provide_inputs()
assert len(inputs) == 1

# Simulate receiving inputs from another provider
result = bed.finalize(received_inputs=[MyProviderInputs(flag=True)])
assert result.some_field == 'derived-from-input'
```

---

## Full example

```python
from pathlib import Path

import pytest

from my_provider.repolish.models import MyProviderContext
from my_provider.repolish.provider import MyProvider
from repolish.testing import ProviderTestBed, assert_snapshots

SNAPSHOT_DIR = Path(__file__).parent / 'snapshots' / 'my_provider'


class TestMyProvider:
    def test_default_context(self) -> None:
        bed = ProviderTestBed(MyProvider)
        ctx = bed.resolved_context
        assert isinstance(ctx, MyProviderContext)
        assert ctx.project_name == 'my-project'

    def test_file_mappings(self) -> None:
        bed = ProviderTestBed(MyProvider)
        fm = bed.file_mappings()
        assert 'README.md' in fm
        assert fm.get('SETUP.md') is not None

    def test_anchors(self) -> None:
        bed = ProviderTestBed(MyProvider)
        anchors = bed.anchors()
        assert 'project-name' in anchors

    def test_render_all_matches_snapshots(self) -> None:
        bed = ProviderTestBed(MyProvider)
        rendered = bed.render_all()
        assert_snapshots(rendered, SNAPSHOT_DIR)

    def test_custom_context_changes_output(self) -> None:
        bed = ProviderTestBed(
            MyProvider,
            context=MyProviderContext(project_name='custom'),
        )
        rendered = bed.render_all()
        assert 'custom' in rendered['README.md']
```
