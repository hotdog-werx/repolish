This guide assumes you have mise installed. This will help you get all the tools
needed to create the monorepo and the providers.

## Bootstrap the monorepo

Start with an empty repo and add the following bootstrap file.

```toml
[settings]
experimental = true
python.uv_venv_auto = true

[tools]
"uv" = "0.10.10"
"repolish" = "1.0.0"
```

Then run `mise install` to get the tools.

## Workspace Provider

This provider should be in charge of the main structure of repos. It will also
take charge of the mise file itself and allow other providers to add their
dependencies to it.

Begin with the following `pyproject.toml` file:

```toml
[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = [] # to be filled later as we need dev tools

[tool.releez]
base-branch = "master"
create-pr = true
alias-version = "major"

[[tool.releez.projects]]
name = "workspace"
path = "packages/workspace"
tag-prefix = "workspace-"
changelog-path = "CHANGELOG.md"
include-paths = ["pyproject.toml", "uv.lock"]

[tool.releez.projects.hooks]
post-changelog = [
  ["uv", "version", "--directory", "packages/workspace", "{version}"],
  ["git", "add", "uv.lock"],
]
```

The `[[tools.releez.projects]]` section is used to configure the release process
for the workspace provider. This section along with its releez project hooks
will have to be duplicated for all providers in the monorepo as we add them.

Create a simple gitignre file which later will be expanded by the provider
responsible for it. This will avoid having to deal with generated files before
the provider is setup and ready to manage them.

```
.venv
__pycache__
.repolish
```

Next create the workspace package with the following repolish command

```bash
repolish scaffold packages/workspace -p devkit.workspace
```

This will create the structure of the new provider. The package on it's own is
empty but it can already be used to to manage the monorepo itself. We'll start
by adding the mise file to take control of it and then make sure that repolish
is working correctly.

Finish this section by making sure that the `packages/workspace/pyproject.toml`
points to the desired version of `repolish` and run
`uv lock -U && uv sync --all-groups`. You may need to open up a new terminal for
`mise` to activate the new virtual environment.

Be sure to commit the changes so far before moving to keep track of your
changes. Once committed you can try out the workspace linker cli to make sure
that the provider is setup correctly.

```
devkit-workspace-link --info
{
    "resources_dir": "..."
    "..."
}
```

## Repolish Config

Create the file `repolish.yaml` with the following

```yaml
providers:
  workspace: devkit-workspace-link
```

From here you can run `repolish link` and verify that the
`.repolish/devkit-workspace` points to the resouces from the package. Then run
`repolish apply` to verify that that repolish can run without any issues.
