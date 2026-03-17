# TODO

## Move symlink creation to post-render phase

Currently `apply_provider_symlinks` is called in `commands/apply.py` **before**
template staging, which means symlinks are created from a freshly instantiated
`Provider` subclass in `_symlinks_from_module` rather than from the fully
hydrated provider instance built during the normal load/render pipeline.

**Goal:** move symlink creation to the end of the apply pipeline — after all
templates have been rendered — so that:

1. Symlinks are created from the same provider instances used for rendering (no
   second instantiation).
2. Symlinks can be displayed in a dedicated table in the apply summary output,
   sitting alongside the existing per-provider file table so the user sees
   everything each provider contributes in one place.

**Rough plan:**

- Remove the early `apply_provider_symlinks(...)` call from `command()` in
  `repolish/commands/apply.py`.
- Collect the resolved symlink list per provider during the build phase
  (alongside `file_mappings`, `anchors`, etc.).
- Execute symlink creation after `render_templates` / `apply_file_mappings`.
- Add a "Symlinks" table (or additional columns) to the Rich summary printed at
  the end of `apply`, showing `source → target` for each provider.
- Update `--check` mode to also verify that expected symlinks exist and point to
  the correct source.

## Fix non-serializable objects in structured log context

Running `repolish -vv` crashes when a log call passes a structured context value
(e.g. a Pydantic model, `Path`, or custom object) that the logging backend
cannot serialize. This surfaces repeatedly whenever new log events are added.

**Goal:** make verbose logging robust so `-vv` never raises a serialization
error regardless of what is passed as context.

**Options to investigate:**

- Fix in **hotlog**: add a fallback serializer (e.g. `repr()` / `str()`) for
  unknown types, similar to `json.dumps(default=str)`, so unserializable values
  degrade gracefully instead of crashing.
- Fix at **call sites**: audit log calls in repolish that pass rich objects and
  convert them to safe primitives before logging (e.g. `str(path)`,
  `model.model_dump()`).
- Likely the right long-term fix lives in hotlog, with call-site cleanups as a
  secondary hardening step.
