# TODO

## Split `commands/apply/` into focused modules

### Vocabulary ✅

Each directory context (standalone project, monorepo root, or monorepo member)
is a **session** — a bounded group of providers that share information with each
other. A repository has one session (standalone) or many (one per member +
root). Session terminology replaces "pass" and "monorepo" throughout.

The session vocabulary is implemented: `ResolvedSession` (in `options.py`),
`resolve_session` and `apply_session` (in `pipeline.py` and `command.py`),
and the resolve/apply split in `coordinator.py`.

### `command.py` → multiple modules

- `pipeline.py` — `resolve_session()`, `_collect_session_outputs`,
  `_alias_pid_maps`, `_ordered_aliases` ✅ _(created; `run_session` stays in
  `command.py` as a thin wrapper around `resolve_session` + `apply_session`)_
- `staging.py` — `_create_staged_template`, `_gather_template_directories`,
  `_collect_excluded_sources`, `_alias_pid_maps`, `_ordered_aliases`,
  `_build_provider_overrides` (from coordinator)
- `symlinks.py` — `_apply_symlinks`, `_check_symlinks`, `_check_one_symlink`
- `debug.py` — `_write_provider_debug_files`, `_debug_file_slug`,
  `_collect_provider_files`
- `display.py` — `_log_providers_summary`, `_print_provider_panels`,
  `_build_provider_panel`, `_role_label`, `_print_files_summary`,
  `_build_provider_table`, `_MODE_STYLE`
- `check.py` — `_finish_check`, `_render_templates`

### `monorepo.py` → `coordinator.py` ✅

- No separate `dry_pass.py` needed — the dry pass is absorbed into
  `pipeline.py::_collect_session_outputs` and called automatically by
  `resolve_session`. `collect_member_data` and `MemberDryRunData` were
  removed; their work is now done by `resolve_session` returning a
  `ResolvedSession` with `provider_entries` and `emitted_inputs` fields.
- `coordinator.py` — `coordinate_sessions`, `_build_global_context`, `_chdir`
  ✅ _(refactored; `_invoke_session` was not needed — `resolve_session` +
  `apply_session` are called directly in the resolve/apply split)_

### Call chain ✅

**Standalone:**
```
apply_command → coordinate_sessions → run_session
                                      (resolve_session + apply_session)
```

**Monorepo:**
```
apply_command → coordinate_sessions
                 ├─ resolve phase: resolve_session × N  (members, then root)
                 └─ apply phase:  apply_session  × N  (root, then members)
```

`coordinate_sessions` detects the repository topology, runs the resolve phase
for all sessions (gaining full visibility into cross-session data flows before
any files are written), then runs the apply phase in order.
`resolve_session` (in `pipeline.py`) owns the full provider pipeline for one
session and returns a `ResolvedSession` with no filesystem side effects.
`apply_session` (in `command.py`) takes a `ResolvedSession` and writes files.
`run_session` (in `command.py`) is the convenience wrapper that does both in
one call — used by standalone mode and the public API.

### `__init__.py` ✅

Current public API: `apply_command`, `ApplyCommandOptions`, `ApplyOptions`,
`ResolvedSession`, `apply_session`, `resolve_session`, `run_session`.

### Public API promotion

Functions that return a meaningful value and have no filesystem side effects
should lose the underscore so tests can import them without reaching into
private internals.

- `display.py` `_print_files_summary` → `print_files_summary` — **already
  imported in tests**, no-brainer
- `display.py` `_build_provider_table` → `build_provider_table` — returns a Rich
  `Table`; tests can assert on its rows
- `display.py` `_build_provider_panel` → `build_provider_panel` — returns a Rich
  `Panel`; testable without IO
- `display.py` `_role_label` → `role_label` — pure function; classifies a
  provider's session role
- `symlinks.py` `_check_symlinks` → `check_symlinks` — returns a `list[str]` of
  issues; no side effects
- `debug.py` `_collect_provider_files` → `collect_provider_files` — pure
  `Providers` → `list[dict]` transform
- `staging.py` `_gather_template_directories` → `gather_template_directories` —
  pure `RepolishConfig` → `list` transform; tests want to verify provider
  ordering

Functions that stay private (pure helpers with no standalone test value, or
side-effectful orchestration steps): `_create_staged_template`,
`_collect_excluded_sources`, `_alias_pid_maps`, `_ordered_aliases`,
`_build_provider_overrides`, `_check_one_symlink`, `_apply_symlinks`,
`_write_provider_debug_files`, `_debug_file_slug`, `_print_provider_panels`,
`_log_providers_summary`, `_finish_check`, `_render_templates`,
`_invoke_session`, `_build_global_context`, `_chdir`.

### Dataclass grouping for wide signatures

Two functions have too many parameters (`# noqa: PLR0913`) and should get a
companion `@dataclass` so callers don't pass positional soup:

- `_finish_check` (7 params) → introduce `CheckResult` or `CheckContext`
  dataclass; fields: `setup_output`, `providers`, `base_dir`, `paused`,
  `resolved_symlinks`, `provider_infos`, `disable_auto_staging`
- `_log_providers_summary` (5 params) → bundle
  `(providers, aliases, alias_to_pid, resolved_symlinks)` into a lightweight
  context struct; `global_context` stays a kwarg

### Notes

- `_build_provider_overrides` belongs in `staging.py` — same profile as
  `_alias_pid_maps` / `_ordered_aliases`: all derive structured data from
  `RepolishConfig`.
- `MemberDryRunData` was removed — `ResolvedSession.provider_entries` and
  `ResolvedSession.emitted_inputs` carry its data instead. ✅
- Model renames will follow naturally: `MonorepoContext` and related names in
  `loader/models` may benefit from session-scoped terminology once the command
  layer is settled.
- The circular-import workaround in `coordinator.py` (deferred
  `from repolish.commands.apply import ...`) was replaced with direct top-level
  imports from `command`, `options`, and `pipeline`. ✅

---

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
