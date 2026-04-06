# Preserve Your Edits with Anchors

Anchors let you mark sections in your files that repolish must never overwrite.
The provider sets a default, you write what you need, and repolish preserves
your version on every subsequent apply.

This is not an escape hatch for emergencies — it is a designed-in feature for
content that genuinely belongs to the project rather than the provider.

## Block anchors

Place matching markers around any block you want to own:

```
## repolish-start[my-section]
...your content here...
## repolish-end[my-section]
```

The marker style (`##`) can be any comment prefix that fits the file type — `#`,
`//`, `--`, etc. What matters is the `repolish-start[name]` /
`repolish-end[name]` text.

### How it works

Block anchor replacements come from the **provider**, not from your project
file. The provider's `create_anchors()` method (or the `anchors:` key in
`repolish.yaml`) returns a dict mapping anchor names to replacement strings.

1. The provider's template ships the anchor with default content between the
   markers.
2. During preprocessing, repolish replaces the block with whatever the
   provider's `create_anchors()` returns for that key.
3. If the provider returns nothing for a key, the default content is kept.
4. The marker lines are stripped from the final written file.

This means the provider decides what the block contains on every apply. To keep
a section static from the provider's perspective, the provider simply returns
the same value every time. For sections you want to own entirely, see
[`paused_files`](pause.md) instead.

### Example — provider injects custom install extras

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

## Regex anchors

For single-line values (versions, config entries, etc.) use a regex anchor
instead of a block:

```
## repolish-regex[my-version]: __version__ = "(.+?)"
__version__ = "0.0.0"
```

Repolish runs the pattern against the current file. If a match is found, the
captured group replaces the line. If not, the default line is used.

### Example — preserving a version string

Provider template:

```python
## repolish-regex[version]: __version__ = "(.+?)"
__version__ = "0.0.0"
```

Your file already contains `__version__ = "1.4.2"`. After every apply that line
stays `1.4.2`. The default `0.0.0` is only used when the file does not exist
yet.

## When anchors are the right tool

Use anchors when the provider intentionally leaves a section for you to fill in
— project description, custom dependencies, local CI steps. They are a
collaborative contract between the provider and your project.

Use [`paused_files`](pause.md) when you want to own the _whole file_ and not
just a section of it.

## Further reading

The [Preprocessors guide](../how-it-works/preprocessors.md) covers multiregex
anchors (matched blocks within a larger list), processing order, and debugging
with `repolish-debugger`.
