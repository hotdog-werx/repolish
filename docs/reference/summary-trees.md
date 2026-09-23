# Summary Trees

Every `repolish apply` run ends with one or two summary trees: the **apply
summary** (always printed) and the **post-process summary** (printed when any
session ran `post_process` commands). `repolish
apply --check` prints the same
trees, reporting the same states a full apply would produce.

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
   `validators:` and `insertions:` detail lines beneath them. Root groups also
   nest a `Promoted` section for files promoted from member sessions to the repo
   root.

## Markers

| Marker | State                                   | Meaning                                                                                                                 |
| ------ | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `✓`    | written                                 | The file was written to the project (green).                                                                            |
| `~`    | unchanged                               | The project file already matched the rendered output (dim cyan).                                                        |
| `✗`    | deleted                                 | A `delete` file mode removed the file (dim red).                                                                        |
| `✗`    | drift                                   | The project file differs from the rendered output (red). In check mode this is the state to watch for.                  |
| `✗`    | paused                                  | A `paused_files` entry matched this file; repolish left it alone (yellow).                                              |
| `✗`    | suppressed                              | The template is suppressed via a `None` mapping (yellow).                                                               |
| `✗`    | disabled                                | The template is disabled via config overrides (yellow).                                                                 |
| `✗`    | not in create_file_mappings (root mode) | In a monorepo root pass the file is not claimed by `create_file_mappings`, so it is never written to the root (yellow). |
| `◌`    | insertion only                          | Nothing was written for this file; the provider only manages insertion blocks inside it (yellow).                       |
| `◌`    | validator only                          | Nothing was written for this file; the provider only validates it (yellow).                                             |
| `📋`   | copy active                             | The resource copy was made (yellow).                                                                                    |
| `⏸`    | copy paused                             | A `paused_files` entry matched the whole copy target; nothing was copied (yellow).                                      |
| `◐`    | copy partially paused                   | A directory copy where some files inside it were held back by `paused_files` (yellow).                                  |
| `↗`    | symlink                                 | The provider symlink was created (blue). The row shows `target → source`.                                               |
| `↑`    | promoted written                        | A member file was promoted and written to the root (green).                                                             |
| `↑`    | promoted differs                        | The promoted file differs from what the member session rendered (yellow).                                               |
| `↑`    | promoted overridden                     | The root pass overrode the promoted file with its own template (yellow, `⚠ overridden by <owner>`).                     |
| `✓`    | command ok                              | A post-process command exited 0 (green).                                                                                |
| `✗`    | command failed                          | A post-process command exited non-zero (red, with the error or exit code).                                              |
| `✗`    | command not run                         | The command was skipped because a previous one failed (yellow).                                                         |

Validator lines under a file use the same glyphs with their own meanings:

| Marker | Meaning                                                             |
| ------ | ------------------------------------------------------------------- |
| `✓`    | The validator ran and passed. A pass shows only the validator name. |
| `⚠`    | The validator reported a warning, shown as `name: message`.         |
| `✗`    | The validator reported an error, shown as `name: message`.          |
| `✗`    | The validator is disabled; the line reads `name: disabled`.         |

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
  report, or the post-process report.

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

## Check mode parity

`repolish apply --check` derives the summary from the same state contract as a
full apply. Paused files, paused and partially paused copies, suppressed and
disabled templates, and validator results all report exactly what
`repolish apply` would do, because check mode computes the held-back copy
targets the same way the copy pass does. The one difference is the states
themselves: check mode reports `drift` where apply reports `written`.
