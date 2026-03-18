# TODO

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


## apply

commands/apply/
    __init__.py          # re-exports apply_command, ApplyCommandOptions (public API)
    options.py           # ApplyOptions, ApplyCommandOptions dataclasses
    dispatch.py          # apply_command() — guard check + standalone/monorepo routing
    pipeline.py          # command() — the full single-pass pipeline orchestration
    staging.py           # _create_staged_template, _gather_template_directories,
                         # _collect_excluded_sources, _alias_pid_maps, _ordered_aliases
    symlinks.py          # _apply_symlinks, _check_symlinks, _check_one_symlink
    debug.py             # _write_provider_debug_files, _debug_file_slug, _collect_provider_files
    display.py           # _log_providers_summary, _print_provider_panels, 
                         # _build_provider_panel, _role_label, _print_files_summary,
                         # _build_provider_table, _MODE_STYLE
    check.py             # _finish_check, _render_templates
