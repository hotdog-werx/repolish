#!/bin/bash
set -xeuo pipefail

uv python install --default --preview 3.11

if [[ -z $(command -v python3) ]]; then
  echo "Python 3.11 not found"
  exit 1
fi
