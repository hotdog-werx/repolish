#!/bin/bash

repo_name=$(basename $(git rev-parse --show-toplevel))
export VIRTUAL_ENV="/opt/uv/${repo_name}"
export UV_PROJECT_ENVIRONMENT="$VIRTUAL_ENV"
if [ ! -d "$VIRTUAL_ENV" ]; then
    uv venv "$VIRTUAL_ENV"
fi
export PATH="$VIRTUAL_ENV/bin:$PATH"
. "$VIRTUAL_ENV/bin/activate"
