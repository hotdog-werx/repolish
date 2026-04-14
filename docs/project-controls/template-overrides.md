# Override a Template

`template_overrides` lets you decide exactly which provider supplies a given
file, regardless of the normal provider ordering rules. You can also use it to
suppress a file entirely so no provider can write it.

## Pin a file to a specific provider

When multiple providers ship the same file, the last one in `providers_order`
wins by default. Use `template_overrides` to change that:

```yaml
providers_order: [base, team]

providers:
  base:
    cli: base-link
  team:
    cli: team-link

template_overrides:
  README.md: base # always use base's README, even though team comes last
```

The value must be a provider alias defined in the `providers` section. Repolish
validates this at load time and will report an error if the alias does not
exist.

## Suppress a file entirely

Set the value to `null` (or `~` in YAML) to tell repolish that no provider
should write this file. It will not be staged, rendered, or compared:

```yaml
template_overrides:
  CODEOWNERS: ~ # we manage this manually
  .editorconfig: null # not relevant for this project
```

A suppressed file is excluded from `--check` diffs and from `apply`. Your local
copy, if any, is untouched.

## Glob patterns

Keys support POSIX glob patterns, so you can pin or suppress a whole directory
at once:

```yaml
template_overrides:
  docs/*: local # all files under docs/ come from the local provider
  .github/workflows/*: ~ # we own all CI files ourselves
```

!!! note Glob matching uses the standard `fnmatch` rules. `*` matches within a
single path segment; it does not cross directory boundaries. Use `**/*.yml` to
match across directories.

## Comparison with `paused_files`

|                                  | `paused_files`              | `template_overrides: null` |
| -------------------------------- | --------------------------- | -------------------------- |
| Intent                           | Temporary workaround        | Permanent exclusion        |
| The file is skipped in `--check` | Yes                         | Yes                        |
| The file is skipped in `apply`   | Yes                         | Yes                        |
| Removal steps                    | Delete the entry when fixed | Leave it in place          |
| Provider template still exists   | Yes                         | Yes (just never used)      |

Use `paused_files` when you expect to resume management soon. Use
`template_overrides: null` when this project will never be managed for that
file.
