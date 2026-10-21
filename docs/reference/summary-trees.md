# Summary Trees

Every `repolish apply` run ends with one or two summary trees: the **apply
summary** (always printed) and the **post-process summary** (printed when any
session ran `post_process` commands). `repolish
apply --check` prints the same
trees, reporting the same states a full apply would produce. A `repolish link`
run ends with its own pair: the **link summary** and the **copy summary**.

This page documents how to read them: the tree structure, every marker, every
annotation, and the hyperlinks each row can carry.

## The apply summary

```
apply summary
└── Standalone
    └── demo@  2 written · 1 unchanged
        ├── ✓ README.md
        ├── ~ pyproject.toml
        ├── ◌ .gitignore  developer owned
        │     insertions: ✓ ok (1 ok, 0 failed)
        └── 📋 configs  ← demo/configs
```

The tree has three levels:

1. **Role groups**: `Root`, `Member: <name>`, or `Standalone`, one per session
   that ran. A monorepo run prints a group per member plus the root pass; a
   standalone project prints a single `Standalone` group.
2. **Provider branches**: one per provider, labeled `alias@version`. The suffix
   after the branch counts what happened to that provider's files:
   `2 written · 1 unchanged` after an apply, or
   `[N applied, M not applied, K copies]` before any file was written.
3. **Rows**: one per managed file, symlink, and resource copy. Files can carry
   `validators:` and `insertions:` detail lines beneath them. A provider whose
   hook raised during the pipeline leads its branch with one red `hook failed`
   row per recorded failure, above the work that did land. Root groups also nest
   a `Promoted` section for files promoted from member sessions to the repo
   root.

## Markers

Every row state draws with its own marker. The tables below are generated from
the marker table in repolish itself, so they are always complete: every state,
verbatim, with no curated subset.

<!-- repolish:on:marker-rows summary-markers rows -->

**File rows**

| Marker | State                                     | Meaning                                                                                                        |
| ------ | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `✓`    | `written`                                 | The file was written to the project.                                                                           |
| `~`    | `unchanged`                               | The project file already matched the rendered output.                                                          |
| `✗`    | `deleted`                                 | A `delete` file mode removed the file.                                                                         |
| `✗`    | `drift`                                   | The project file differs from the rendered output. In check mode this is the state to watch for.               |
| `✗`    | `paused`                                  | A `paused_files` entry matched this file; repolish left it alone.                                              |
| `✗`    | `suppressed`                              | The template is suppressed via a `None` mapping.                                                               |
| `✗`    | `disabled`                                | The template is disabled via config overrides.                                                                 |
| `✗`    | `not in create_file_mappings (root mode)` | In a monorepo root pass the file is not claimed by `create_file_mappings`, so it is never written to the root. |
| `◌`    | `insertion only`                          | Nothing was written for this file; the provider only manages insertion blocks inside it.                       |
| `◌`    | `validator only`                          | Nothing was written for this file; the provider only validates it.                                             |
| `✓`    | `ok`                                      | The file is clean: a row that carries validator lines beneath it, or a matching file in check mode.            |

**Resource copies**

| Marker | State              | Meaning                                                                       |
| ------ | ------------------ | ----------------------------------------------------------------------------- |
| `📋`   | `active`           | The resource copy was made.                                                   |
| `⏸`    | `paused`           | A `paused_files` entry matched the whole copy target; nothing was copied.     |
| `◐`    | `partially paused` | A directory copy where some files inside it were held back by `paused_files`. |

**Promoted files**

| Marker | State                | Meaning                                                                 |
| ------ | -------------------- | ----------------------------------------------------------------------- |
| `↑`    | `written`            | A member file was promoted and written to the root.                     |
| `~`    | `unchanged`          | The promoted file already matched what the member session rendered.     |
| `↑`    | `differs`            | The promoted file differs from what the member session rendered.        |
| `↑`    | `overridden_by_root` | The root pass overrode the promoted file with its own template.         |
| `✗`    | `paused`             | A `paused_files` entry matched the promoted file, so it was left alone. |
| `✗`    | `suppressed`         | The promoted template is suppressed, so nothing was written for it.     |

**Post-process commands**

| Marker | State     | Meaning                                                                           |
| ------ | --------- | --------------------------------------------------------------------------------- |
| `✓`    | `ok`      | The post-process command exited 0.                                                |
| `✗`    | `failed`  | The post-process command exited non-zero, showing the error message or exit code. |
| `✗`    | `not_run` | The command was skipped because a previous one failed.                            |
| `-`    | `skipped` | The scoped command ran nothing: no generated files matched its `files` patterns.  |

**Hook failures**

| Marker | State    | Meaning                                                                                                                                        |
| ------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `✗`    | `failed` | A provider or facet hook raised and was skipped. The row reads `<hook> failed`, plus `(facet <name>)` for a facet hook, and the error message. |

<!-- repolish:off:marker-rows -->

Symlink rows have no state of their own and stay outside the table: a provider
symlink row draws `↗` (blue) and shows `target → source`.

Validator lines under a file use the same glyphs with their own meanings:

<!-- repolish:on:validator-lines summary-markers validator-lines -->

**Validator lines**

| Marker | State      | Meaning                                                             |
| ------ | ---------- | ------------------------------------------------------------------- |
| `✓`    | `pass`     | The validator ran and passed. A pass shows only the validator name. |
| `⚠`    | `warning`  | The validator reported a warning, shown as `name: message`.         |
| `✗`    | `error`    | The validator reported an error, shown as `name: message`.          |
| `✗`    | `disabled` | The validator is disabled; the line reads `name: disabled`.         |

<!-- repolish:off:validator-lines -->

The `insertions:` line beneath a file shows one of:

- `insertions: ✓ ok (N ok, M failed, K disabled)` when every block landed (dim
  green)
- `insertions: ✗ failed (...)` when any block failed (yellow)

## Annotations

After the path, a file row can carry several dim notes:

- **Mode note**: `create_only` or `keep`, when the file mode is not the default
  `regular` mode. `delete` files show no note.
- **Source**: `← <source>` shows which provider template produced the file.
- **Ownership**: `developer owned` (repolish did not write this file, it only
  manages parts of it), `possibly provider-owned` (same, but a provider filter
  ran so the true owner may be an excluded provider), or `owned by <alias>`
  (another provider claims the path).
- **State notes**: `paused`, `suppressed`, `disabled`, and the root-mode skip
  reason, described in the marker table above.

## Links

In terminals that support hyperlinks, three kinds of links ride on the trees.
Each opens a local file:

- The **file name** in a file row links to that file's `file-context` debug JSON
  under `.repolish/_/file-ctx/`: the exact context the template was rendered
  with.
- The **provider alias** in a branch label links to the provider's
  `provider-context` JSON under `.repolish/_/`.
- A **`[details]`** suffix links to the report behind a block of rows: the
  per-file validator report under `.repolish/_/validators/`, the insertion
  report, the post-process report, or the `hook-failures` JSON behind a
  `hook failed` row.

When the terminal does not support hyperlinks the links are omitted and the
report paths stay reachable through the `.repolish` directory.

## The post-process summary

```
post-process summary
└── demo  2 ok · 1 failed [details]
    ├── ✓ make fmt  ok (183ms)
    ├── ✓ make lint  ok (1.2s)
    └── ✗ make test  FAILED exit 1
```

One group per session that ran `post_process` commands, labeled with the member
name, `root`, or the standalone directory name, plus
`N ok · M failed · K not run` counts. Each command row repeats the raw command
with its outcome and duration. A failed command shows the error message or exit
code; commands after a failure show `not run (previous command failed)`.

## The link summaries

```
link summary
└── Standalone
    └── demo
        └── ↗ .editorconfig  → demo/editorconfig

copy summary
└── Standalone
    └── demo
        ├── 📋 configs  ← demo/configs
        └── ⏸ dprint.json  ← demo/dprint.json (paused)
```

`repolish link` prints the **link summary** when any provider resolved symlinks
and the **copy summary** when any resolved resource copies; both are silent when
unused. The groups are the same role groups as the apply summary (`Root`,
`Member: <name>`, `Standalone`), one per config that was linked, with one branch
per provider alias.

The copy rows use the same markers as the apply summary, so a paused or
partially paused copy reads identically after both commands. The copy summary
reflects what repolish _would_ do, including the copies it skipped because the
project paused them.

## Check mode parity

`repolish apply --check` derives the summary from the same state contract as a
full apply. Paused files, paused and partially paused copies, suppressed and
disabled templates, and validator results all report exactly what
`repolish apply` would do, because check mode computes the held-back copy
targets the same way the copy pass does. The one difference is the states
themselves: check mode reports `drift` where apply reports `written`.
