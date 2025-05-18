#!/bin/bash
set -xeuo pipefail

uvVersion=0.6.3
curl -LsSf "https://github.com/astral-sh/uv/releases/download/${uvVersion}/uv-installer.sh" | sh
