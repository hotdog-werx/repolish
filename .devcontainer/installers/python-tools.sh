#!/bin/bash
set -xeuo pipefail

# tools should not be linked
export UV_LINK_MODE="copy"

uv tool install "mdformat==0.7.22"
uv tool install "argcomplete==3.5.3"
