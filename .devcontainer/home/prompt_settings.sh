#!/bin/bash

# display repo name
function prompt_context() {
  in_git_repo=$(git rev-parse --is-inside-work-tree 2>/dev/null)
  if [ -n "$in_git_repo" ]; then
    repo_path=$(git rev-parse --show-toplevel)
    repo_name=$(basename "$repo_path")
  else
    repo_name=''
  fi
  name='devcontainer'
  prompt_segment black default "$name"
  if [ -n "$repo_name" ]; then
    prompt_segment green default "$repo_name"
  fi
}

# only show directories relative to the workspace
function prompt_dir {
  repo_path="$CONTAINER_WORKSPACE"
  current_path="${PWD/"$repo_path"/^}"
  if [ "$current_path" != "^" ]; then
    prompt_segment blue default "$current_path"
  fi
}

# do not show python venv
unset OMB_PROMPT_SHOW_PYTHON_VENV
